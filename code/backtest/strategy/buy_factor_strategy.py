"""
Alpha101 因子选股策略

从 config JSON 读取因子配置，
通过 Alpha101Factors 计算因子得分，等权重/加权综合打分后选股。

文件命名含 strategy 以符合策略发现规则。
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

from code.backtest.strategy.protocol import BaseBuyStrategy, BuyResult

# ── 项目路径 ────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
FACTOR_ENGINE_DIR = os.path.join(PROJECT_ROOT,
    '101factor', '101factor_platform', 'src', 'factor_engine')
if FACTOR_ENGINE_DIR not in sys.path:
    sys.path.insert(0, FACTOR_ENGINE_DIR)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'buy_factor.json')


def load_config(config_path: str = None) -> dict:
    """加载买入策略配置"""
    path = config_path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        print(f"[买入策略] 配置文件不存在: {path}，使用默认配置")
        return {
            "factors": ["alpha002", "alpha006"],
            "factor_reverse": False,
            "factor_weights": {},
            "normalization": "zscore",
            "stock_pool": {
                "source": "industry",
                "industry": "创业板",
                "exclude_st": True,
                "exclude_new_stocks_days": 60,
                "min_price": 3.0
            },
            "selection": {"top_n": 10, "min_score": 0},
            "history_days": 60,
            "enable_cache": False,
            "cache_dir": None
        }
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


class BuyStrategy(BaseBuyStrategy):
    """Alpha101 因子买入策略"""

    def __init__(self, config_path: str = None):
        self._config = None
        self._config_path = config_path

    def load_config(self) -> dict:
        if self._config is None:
            self._config = load_config(self._config_path)
        return self._config

    def select(self, date: str, xtdata=None,
               kline_data: pd.DataFrame = None,
               stock_list: list = None) -> BuyResult:
        """执行选股

        Args:
            date: 调仓日期 YYYYMMDD
            xtdata: xtquant 数据对象（可选，用于回退）
            kline_data: 预加载的 MultiIndex DataFrame（优先使用）
            stock_list: 股票池列表（覆盖 config 中的股票池设置）

        Returns:
            BuyResult: 选中的股票列表和价格
        """
        config = self.load_config()
        select_cfg = config.get('selection', {})
        top_n = select_cfg.get('top_n', 10)
        min_score = select_cfg.get('min_score', 0)

        print(f"\n{'='*60}")
        print(f"  Alpha101 因子选股 - {date}")
        print(f"{'='*60}")

        # 1. 确定股票池
        if stock_list is None:
            stock_pool = self._get_stock_pool(config, xtdata)
        else:
            stock_pool = stock_list

        if not stock_pool:
            print("  [买入策略] 股票池为空")
            return BuyResult()

        print(f"  股票池: {len(stock_pool)} 只")

        # 2. 准备 K 线数据
        if kline_data is not None:
            # 使用外部传入的数据
            data = kline_data
        else:
            # 从本地 CSV 加载
            data = self._prepare_data(stock_pool, date, config)

        if data is None or data.empty:
            print("  [买入策略] 数据为空")
            return BuyResult()

        # 3. 计算 Alpha101 因子
        scores = self._compute_scores(data, config, date)

        if scores is None or scores.empty:
            print("  [买入策略] 因子计算无结果")
            return BuyResult()

        # 3.5 用股票池过滤得分
        if stock_pool:
            before = len(scores)
            scores = scores[scores.index.isin(stock_pool)]
            print(f"  股票池过滤: {before} -> {len(scores)} 只")

        # 4. 排序选股
        factor_reverse = config.get('factor_reverse', False)
        sorted_scores = scores.sort_values(ascending=factor_reverse)
        top_stocks = sorted_scores.head(top_n)

        if min_score > 0:
            before = len(top_stocks)
            top_stocks = top_stocks[top_stocks > min_score]
            print(f"  分数过滤 (> {min_score}): {before} -> {len(top_stocks)}")

        selected = top_stocks.index.tolist()
        print(f"  选中: {len(selected)} 只")
        for i, s in enumerate(selected[:10]):
            print(f"    {i+1}. {s}  {top_stocks[s]:.2f}")

        # 5. 获取价格
        prices = self._get_prices(data, date, selected)

        return BuyResult(stocks=selected, prices=prices, date=date,
                          scores=top_stocks.to_dict())

    # 板块前缀映射：用于在无 xtdata 时按板块过滤
    BOARD_PREFIXES = {
        '创业板': ('300', '301'),
        '科创板': ('688',),
        '主板': ('600', '601', '603', '605', '000', '001', '002'),
        '深圳主板': ('000', '001', '002'),
        '上海主板': ('600', '601', '603', '605'),
        '北交所': ('8',),
    }

    def _get_stock_pool(self, config: dict, xtdata) -> list:
        """获取股票池"""
        pool_cfg = config.get('stock_pool', {})
        source = pool_cfg.get('source', 'industry')

        if source == 'list':
            return pool_cfg.get('list', [])

        if source == 'csv':
            csv_path = pool_cfg.get('csv_path', '')
            if os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    return df.iloc[:, 0].dropna().str.strip().tolist()
                except Exception as e:
                    print(f"  [买入策略] CSV 读取失败: {e}")

        if source == 'industry' and xtdata is not None:
            industry = pool_cfg.get('industry', '创业板')
            try:
                stocks = xtdata.get_stock_list_in_sector(industry)
                if stocks:
                    return stocks
            except Exception:
                pass

        # 从 stock_list.csv 读取全量股票池
        csv_path = os.path.join(PROJECT_ROOT, 'core', 'dictionary', 'stock_list.csv')
        if not os.path.exists(csv_path):
            csv_path = os.path.join(PROJECT_ROOT, 'export', 'data', 'stock_list.csv')
        if not os.path.exists(csv_path):
            print(f"  [买入策略] 未找到 stock_list.csv")
            return []

        try:
            df = pd.read_csv(csv_path)
            pool = df.iloc[:, 0].dropna().str.strip().tolist()
        except Exception as e:
            print(f"  [买入策略] 股票池读取失败: {e}")
            return []

        # 按板块/行业过滤
        if source == 'industry':
            industry = pool_cfg.get('industry', '')
            if not industry:
                return pool

            # 按板块前缀过滤（创业板=300/301，科创板=688等）
            prefixes = self.BOARD_PREFIXES.get(industry)
            if prefixes:
                filtered = [s for s in pool if s.startswith(prefixes)]
                print(f"  [买入策略] 板块 '{industry}' 过滤: {len(pool)} -> {len(filtered)} 只")
                return filtered

            # 按申万行业过滤
            sw_path = os.path.join(PROJECT_ROOT, 'core', 'dictionary', 'sw_industry.csv')
            if os.path.exists(sw_path):
                try:
                    sw = pd.read_csv(sw_path)
                    industry_stocks = sw[
                        sw.iloc[:, 1].str.contains(industry, na=False)]
                    industry_codes = set(industry_stocks.iloc[:, 0].tolist())
                    filtered = [s for s in pool if s in industry_codes]
                    print(f"  [买入策略] 申万行业 '{industry}' 过滤: {len(pool)} -> {len(filtered)} 只")
                    return filtered
                except Exception as e:
                    print(f"  [买入策略] 行业过滤失败: {e}")

        return pool

    def _prepare_data(self, stock_list: list, end_date: str, config: dict) -> pd.DataFrame:
        """从本地 CSV 加载 K 线数据"""
        history_days = config.get('history_days', 60)
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=history_days * 2)
        start_str = start_dt.strftime('%Y%m%d')
        end_ts = int(end_dt.timestamp() * 1000)
        start_ts = int(start_dt.timestamp() * 1000)

        kline_dir = os.path.join(PROJECT_ROOT, 'export', 'data', 'kline')
        all_data = []

        for stock in stock_list:
            fp = os.path.join(kline_dir, f'{stock}.csv')
            if not os.path.exists(fp):
                continue
            try:
                df = pd.read_csv(fp)
                df = df[(df['time'] >= start_ts) & (df['time'] <= end_ts)]
                if df.empty:
                    continue
                df['date'] = pd.to_datetime(df['time'], unit='ms')
                df['symbol'] = stock
                all_data.append(df[['date', 'symbol', 'open', 'high', 'low', 'close', 'volume']])
            except Exception:
                continue

        if not all_data:
            return None

        result = pd.concat(all_data, ignore_index=True)
        result = result.set_index(['date', 'symbol']).sort_index()
        return result

    def _compute_scores(self, data: pd.DataFrame, config: dict, date: str) -> pd.Series:
        """计算因子综合得分"""
        from alpha101 import Alpha101Factors

        factors_list = config.get('factors', [])
        if not factors_list:
            print("  [买入策略] 未配置因子")
            return None

        weights = config.get('factor_weights', {})
        norm_method = config.get('normalization', 'zscore')

        calculator = Alpha101Factors(data)

        # 逐个计算因子
        factor_values = {}
        for fname in factors_list:
            if not hasattr(calculator, fname):
                print(f"  [买入策略] 跳过不存在的因子: {fname}")
                continue
            try:
                fval = getattr(calculator, fname)()
                if fval is None or (isinstance(fval, pd.DataFrame) and fval.empty):
                    continue
                # 提取最新日期
                latest = self._extract_latest(fval, date)
                if latest is not None:
                    factor_values[fname] = latest
            except Exception as e:
                print(f"  [买入策略] {fname} 计算失败: {e}")

        if not factor_values:
            return None

        # 因子归一化
        normalized = {}
        for fname, series in factor_values.items():
            normalized[fname] = self._normalize(series, method=norm_method)

        # 综合打分
        base_idx = list(normalized.values())[0].index
        composite = pd.Series(0.0, index=base_idx, dtype=float)

        total_weight = 0
        for fname, series in normalized.items():
            w = weights.get(fname, 1.0)
            composite = composite.add(series.mul(w), fill_value=0)
            total_weight += w

        if total_weight > 0:
            composite = composite / total_weight * len(normalized)

        return composite

    def _extract_latest(self, factor_df: pd.DataFrame, date: str) -> pd.Series:
        """从因子 DataFrame (Date x Stock) 提取最新日期值"""
        if isinstance(factor_df.index, pd.DatetimeIndex):
            target = pd.Timestamp(date)
            available = factor_df.index[factor_df.index <= target]
            if len(available) == 0:
                return None
            latest = available[-1]
            return factor_df.loc[latest]
        return None

    def _normalize(self, series: pd.Series, method: str = 'zscore') -> pd.Series:
        """因子归一化"""
        valid = series.dropna()
        if len(valid) == 0:
            return pd.Series(0.0, index=series.index, dtype=float)

        if method == 'rank':
            result = valid.rank(pct=True) * 100
        elif method == 'zscore':
            mean, std = valid.mean(), valid.std()
            if std > 0:
                # 截尾 ±3σ 防止极端值拉偏，但不 clip 结果以保留区分度
                clipped = valid.clip(mean - 3*std, mean + 3*std)
                result = (clipped - mean) / std * 50 + 50
            else:
                result = pd.Series(50.0, index=valid.index)
        else:  # minmax
            mn, mx = valid.min(), valid.max()
            if mx > mn:
                result = (valid - mn) / (mx - mn) * 100
            else:
                result = pd.Series(50.0, index=valid.index)

        out = pd.Series(0.0, index=series.index, dtype=float)
        out[valid.index] = result
        return out

    def _get_prices(self, data: pd.DataFrame, date: str, stocks: list) -> dict:
        """从数据中获取指定股票在指定日期的收盘价"""
        prices = {}
        target = pd.Timestamp(date)
        try:
            df_date = data.xs(target, level='date', drop_level=False)
            for s in stocks:
                try:
                    p = df_date.loc[(target, s), 'close']
                    prices[s] = float(p)
                except (KeyError, TypeError):
                    continue
        except Exception:
            pass
        return prices
