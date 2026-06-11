"""
长期下跌企稳选股策略

===== 策略逻辑 =====

两段式条件检查：

  第一段（两周前的状态）—— 确认股票处于长期下跌：
    - 从250日最高点回撤 >= 指定百分比（默认30%）
    - 均线空头排列：短期均线(5/10/20) 在 长期均线(60/120) 下方

  第二段（今天的状态）—— 确认股票已止跌企稳：
    - 5日线、10日线走平或上翘（对比14个交易日前）
    - 最近N个交易日没有创新低（最低价未跌破T-14的收盘价水平）
    - 当前收盘价 > 14个交易日前收盘价 × (1 + 指定百分比，默认5%)
    - 当日成交量 > 14个交易日前成交量

===== 文件命名规约 =====

文件名含 strategy 以符合策略发现规则。
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from code.backtest.strategy.protocol import BaseBuyStrategy, BuyResult

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# 策略默认配置文件路径（用户可编辑此文件调整参数，不改代码）
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'buy_reversal.json')

BOARD_PREFIXES = {
    '创业板': ('300', '301'),
    '科创板': ('688',),
    '主板': ('600', '601', '603', '605', '000', '001', '002'),
    '深圳主板': ('000', '001', '002'),
    '上海主板': ('600', '601', '603', '605'),
    '北交所': ('8',),
}


class BuyStrategy(BaseBuyStrategy):
    """长期下跌企稳选股策略"""

    def __init__(self, config_path: str = None):
        self._config = None
        # 如果没传配置路径，自动走默认路径
        self._config_path = config_path or DEFAULT_CONFIG_PATH

    def load_config(self) -> dict:
        if self._config is None:
            self._config = self._default_config()
            if self._config_path and os.path.exists(self._config_path):
                try:
                    with open(self._config_path, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                    # 深层合并（只合并 dict 类型键，标量直接覆盖）
                    for key, val in loaded.items():
                        if (key in self._config and isinstance(val, dict)
                                and isinstance(self._config[key], dict)):
                            self._config[key].update(val)
                        else:
                            self._config[key] = val
                except Exception as e:
                    print(f"  [买入策略] 配置加载失败: {e}")
        return self._config

    def _default_config(self) -> dict:
        return {
            # ==================================================================
            # 第一段：长期下跌判断条件（两周前的状态）
            # ==================================================================
            "decline_filter": {
                # 从250日最高点回撤的最小百分比。
                # 例如 30.0 表示从250日最高跌了30%以上才算"长期下跌"。
                "min_drawdown_pct": 30.0,

                # 均线空头排列：两周前短周期均线是否在长周期均线下方。
                # short = 短周期均线参数列表
                # long  = 长周期均线参数列表
                # 条件：short 中最长的均线 < long 中最短的均线
                #       即 20日均线 < 60日均线
                "ma_death_cross": {
                    "short": [5, 10, 20],
                    "long": [60, 120]
                }
            },

            # ==================================================================
            # 第二段：企稳确认条件（今天的状态）
            # ==================================================================
            "stabilize_filter": {
                # 短期均线走平/上翘的判断窗口（交易日数）。
                # 检查当前MA5是否 >= 14个交易日前的MA5，
                # 且当前MA10是否 >= 14个交易日前的MA10。
                "ma_flat_window": 14,

                # 最近N个交易日没有创新低。
                # 条件：最近N天的最低价 > T-14日的收盘价。
                # 这确保价格没有重新跌回两周前的位置。
                "no_new_low_days": 10,

                # 当前收盘价高于14个交易日前收盘价的最小百分比。
                # 例如 5.0 表示今日收盘价比两周前高了5%以上，
                # 确认不是原地趴着，是真的有反弹。
                "min_price_rise_pct": 5.0
            },

            # ==================================================================
            # 股票池配置
            # ==================================================================
            "stock_pool": {
                # source: industry=按板块, csv=从文件读, list=直接写列表
                "source": "industry",
                # 板块名称，用于 industry 模式
                "industry": "创业板",
                # 是否排除ST/ST*股票
                "exclude_st": True,
                # 上市不足N天的次新股排除
                "exclude_new_stocks_days": 60,
                # 最低股价（低于此价格的排除）
                "min_price": 3.0
            },

            # ==================================================================
            # 选股输出参数
            # ==================================================================
            "selection": {
                # 最多输出多少只候选股票
                "top_n": 20
            },

            # 需要的历史数据天数（250日最高点需要足够数据）
            "history_days": 500
        }

    def select(self, date: str, xtdata=None,
               kline_data: pd.DataFrame = None,
               stock_list: list = None) -> BuyResult:
        """执行选股

        两段式检查：
          1. 两周前是否处于长期下跌（回撤深度 + 均线空头排列）
          2. 现在是否已企稳（均线走平 + 价格站稳 + 量能恢复）

        Args:
            date: 调仓日期 YYYYMMDD
            kline_data: 预加载的 MultiIndex DataFrame（优先使用）
            stock_list: 股票池列表（覆盖 config 中的股票池设置）

        Returns:
            BuyResult: 选中的股票列表
        """
        config = self.load_config()
        select_cfg = config.get('selection', {})
        top_n = select_cfg.get('top_n', 20)

        print(f"\n{'='*60}")
        print(f"  长期下跌企稳选股 - {date}")
        print(f"{'='*60}")

        # 1. 确定股票池
        pool = stock_list if stock_list is not None else self._get_stock_pool(config)
        if not pool:
            print("  [买入策略] 股票池为空")
            return BuyResult()
        print(f"  股票池: {len(pool)} 只")

        # 2. 获取 K 线数据
        data = kline_data if kline_data is not None else self._prepare_data(pool, date, config)
        if data is None or data.empty:
            print("  [买入策略] 数据为空")
            return BuyResult()

        # 3. 逐只股票检查
        candidates = self._screen_stocks(data, config, date, pool)

        if not candidates:
            print("\n  [买入策略] 无股票通过检查")
            return BuyResult()

        # 按股票代码排序输出（排名不分先后，都是候选）
        sorted_codes = sorted(candidates.keys())

        print(f"\n  通过检查: {len(sorted_codes)} 只")
        selected = sorted_codes[:top_n]
        for i, code in enumerate(selected):
            info = candidates[code]
            parts = [
                f"回撤={info['drawdown_pct']:.1f}%",
                f"当前/14日前={info['curr_price']:.2f}/{info['price_14d_ago']:.2f}",
                f"量比={info['volume_ratio']:.2f}"
            ]
            print(f"    {i+1}. {code}  {'  '.join(parts)}")

        # 获取价格用于买入（取最新收盘价）
        end_dt = pd.Timestamp(date)
        prices = {}
        try:
            date_data = data.xs(end_dt, level='date', drop_level=False)
            for s in selected:
                try:
                    p = date_data.loc[(end_dt, s), 'close']
                    prices[s] = float(p)
                except (KeyError, TypeError):
                    continue
        except Exception:
            pass

        return BuyResult(stocks=selected, prices=prices, date=date)

    # ── 核心筛选逻辑 ─────────────────────────────────

    def _screen_stocks(self, data: pd.DataFrame, config: dict,
                       date: str, stock_pool: list) -> dict:
        """逐只股票检查两段式条件"""
        decline_cfg = config.get('decline_filter', {})
        stabilize_cfg = config.get('stabilize_filter', {})

        min_drawdown = decline_cfg.get('min_drawdown_pct', 30.0)
        ma_death = decline_cfg.get('ma_death_cross', {})
        short_periods = ma_death.get('short', [5, 10, 20])
        long_periods = ma_death.get('long', [60, 120])

        ma_window = stabilize_cfg.get('ma_flat_window', 14)
        no_low_days = stabilize_cfg.get('no_new_low_days', 10)
        min_rise = stabilize_cfg.get('min_price_rise_pct', 5.0)

        end_dt = pd.Timestamp(date)

        # 需要的最少交易天数：
        #   - 最长均线（默认120日）需要 T-14 前有足够的交易日
        #   - 加上14日窗口到T，再加20缓冲
        # 注意：250日最高点回撤是软性要求——数据不足时自动使用可用的最远数据
        need_days = max(long_periods) + ma_window + 20

        results = {}
        total = len(stock_pool)

        for idx, stock in enumerate(stock_pool):
            if (idx + 1) % 50 == 0:
                print(f"  进度: {idx+1}/{total}")

            try:
                # 获取该股票的完整日线，按日期排序
                sd = data.xs(stock, level='symbol').sort_index()
                sd = sd[sd.index <= end_dt]
                if len(sd) < need_days:
                    continue
            except KeyError:
                continue

            # 定位 T（今天）和 T-14（14个交易日前）的索引位置
            t_idx = len(sd) - 1
            t14_idx = t_idx - ma_window  # ma_window=14个交易日

            if t14_idx < 0:
                continue

            # ── 第一段检查：两周前的状态（T-14） ──

            # 条件1：从250日高点回撤 >= min_drawdown%
            # 250日 = 约1年交易日。数据不足时尽可能回溯——至少保证60日数据才够意义
            lookback_250 = min(250, t14_idx)
            if lookback_250 < 60:
                continue  # 数据太少，回撤计算没意义
            high_250 = sd['high'].iloc[t14_idx - lookback_250 + 1:t14_idx + 1].max()
            close_t14 = sd['close'].iloc[t14_idx]
            drawdown_pct = (1 - close_t14 / high_250) * 100
            if drawdown_pct < min_drawdown:
                continue

            # 条件2：均线空头排列
            # 检查短周期均线中最长的那条 < 长周期均线中最短的那条
            # 即 MA20 < MA60
            short_max_period = max(short_periods)   # 20
            long_min_period = min(long_periods)     # 60

            if t14_idx - long_min_period < 0:
                continue

            # 在 T-14 时间点计算均线
            ma_short = sd['close'].iloc[t14_idx - short_max_period + 1:t14_idx + 1].mean()
            ma_long = sd['close'].iloc[t14_idx - long_min_period + 1:t14_idx + 1].mean()
            if pd.isna(ma_short) or pd.isna(ma_long):
                continue
            if ma_short >= ma_long:
                continue  # 不是空头排列

            # ── 第二段检查：今天的状态（T） ──

            # 条件3：短期均线走平或上翘
            # 当前 MA5 >= T-14 时的 MA5
            # 且当前 MA10 >= T-14 时的 MA10
            ma5_t = sd['close'].iloc[t_idx - 4:t_idx + 1].mean()
            ma5_t14 = sd['close'].iloc[t14_idx - 4:t14_idx + 1].mean()
            ma10_t = sd['close'].iloc[t_idx - 9:t_idx + 1].mean()
            ma10_t14 = sd['close'].iloc[t14_idx - 9:t14_idx + 1].mean()

            if pd.isna(ma5_t) or pd.isna(ma5_t14) or pd.isna(ma10_t) or pd.isna(ma10_t14):
                continue
            if ma5_t < ma5_t14 or ma10_t < ma10_t14:
                continue

            # 条件4：最近N个交易日没有再创新低
            # 条件：最近 N 天的最低价 > T-14 的收盘价（即没有回到两周前的位置）
            low_n = sd['low'].iloc[t_idx - no_low_days + 1:t_idx + 1].min()
            if low_n <= close_t14:
                continue

            # 条件5：当前收盘价 > T-14 收盘价 × (1 + min_rise%)
            close_t = sd['close'].iloc[t_idx]
            price_rise_pct = (close_t / close_t14 - 1) * 100
            if price_rise_pct < min_rise:
                continue

            # 条件6：今日成交量 > T-14 成交量
            vol_t = sd['volume'].iloc[t_idx]
            vol_t14 = sd['volume'].iloc[t14_idx]
            if vol_t <= vol_t14:
                continue

            # 全部条件通过：这是一个候选
            info = {
                'drawdown_pct': round(drawdown_pct, 1),
                'price_14d_ago': round(close_t14, 2),
                'curr_price': round(close_t, 2),
                'price_rise_pct': round(price_rise_pct, 1),
                'volume_ratio': round(vol_t / vol_t14 if vol_t14 > 0 else 0, 2),
                'ma5_t': round(ma5_t, 2),
                'ma5_t14': round(ma5_t14, 2),
                'ma10_t': round(ma10_t, 2),
                'ma10_t14': round(ma10_t14, 2)
            }
            results[stock] = info

        return results

    # ── 数据加载 ─────────────────────────────────────

    def _get_stock_pool(self, config: dict) -> list:
        """获取股票池（同强势整理策略）"""
        pool_cfg = config.get('stock_pool', {})
        source = pool_cfg.get('source', 'industry')

        if source == 'list':
            return pool_cfg.get('list', [])

        if source == 'csv':
            csv_path = pool_cfg.get('csv_path', '')
            full = os.path.join(PROJECT_ROOT, csv_path) if csv_path else ''
            if os.path.exists(full):
                try:
                    df = pd.read_csv(full)
                    return df.iloc[:, 0].dropna().str.strip().tolist()
                except Exception as e:
                    print(f"  [买入策略] CSV读取失败: {e}")

        if source == 'industry':
            industry = pool_cfg.get('industry', '创业板')
            prefixes = BOARD_PREFIXES.get(industry)
            csv_path = os.path.join(PROJECT_ROOT, 'core', 'dictionary', 'stock_list.csv')
            if not os.path.exists(csv_path):
                csv_path = os.path.join(PROJECT_ROOT, 'export', 'data', 'stock_list.csv')
            if os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    pool = df.iloc[:, 0].dropna().str.strip().tolist()
                    if prefixes:
                        pool = [s for s in pool if s.startswith(prefixes)]
                    return pool
                except Exception:
                    pass

        return []

    def _prepare_data(self, stock_list: list, end_date: str, config: dict) -> pd.DataFrame:
        """从本地 CSV 加载 K 线数据"""
        history_days = config.get('history_days', 500)
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=history_days)
        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)

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
