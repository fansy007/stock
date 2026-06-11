"""
强势整理买点策略

两段式漏斗：
  1. 强势熔断（硬条件过滤）——前期涨幅、放量确认、创过新高
  2. 整理质量评分（软排名）——缩量、波动收缩、均线支撑、OBV背离、ADX

命名含 strategy 以符合策略发现规则。
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

from code.backtest.strategy.protocol import BaseBuyStrategy, BuyResult

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# 板块前缀映射
BOARD_PREFIXES = {
    '创业板': ('300', '301'),
    '科创板': ('688',),
    '主板': ('600', '601', '603', '605', '000', '001', '002'),
    '深圳主板': ('000', '001', '002'),
    '上海主板': ('600', '601', '603', '605'),
    '北交所': ('8',),
}


class BuyStrategy(BaseBuyStrategy):
    """强势整理买点策略"""

    def __init__(self, config_path: str = None):
        self._config = None
        self._config_path = config_path

    def load_config(self) -> dict:
        if self._config is None:
            self._config = self._default_config()
            if self._config_path and os.path.exists(self._config_path):
                try:
                    with open(self._config_path, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
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
            "_comment_strong": "===== 第一段：强势熔断（硬条件，全满足才放行） =====",
            "strong_filter": {
                "_comment_return": "过去N天涨幅门槛（%），低于此的股票直接淘汰",
                "return_days": 20,
                "min_return_pct": 15.0,
                "_comment_volume": "过去N天均量 / 前N天均量，低于此比例说明没放量",
                "volume_days": 20,
                "min_volume_ratio": 1.5,
                "_comment_new_high": "过去N天内是否创过X日新高",
                "new_high_days": 20,
                "new_high_lookback": 60,
            },
            "_comment_score": "===== 第二段：整理质量评分（软条件，满分100） =====",
            "consolidation_scoring": {
                "_comment_volume": "成交量萎缩至N日均量的比例，越低说明缩量越充分",
                "volume_shrink_pct": 0.6,
                "_comment_volatility": "是否启用波动率收窄评分（布林带带宽收缩程度）",
                "volatility_contraction": True,
                "_comment_ma": "均线支撑类型: MA20 / MA60 / BOTH / NONE",
                "ma_support": "MA20",
                "_comment_obv": "是否启用OBV背离评分（价格回调但OBV不新低=资金没跑）",
                "obv_divergence": True,
                "_comment_days": "整理天数合理区间（太短洗盘不充分，太长强势变弱）",
                "min_consolidation_days": 5,
                "max_consolidation_days": 25,
                "_comment_adx": "是否启用ADX评分（ADX低=无趋势=蓄力阶段）",
                "adx_low": True,
            },
            "_comment_pool": "===== 股票池配置（同因子选股策略） =====",
            "stock_pool": {
                "_comment": "source: industry=按板块, csv=从文件读, list=直接写列表",
                "source": "csv",
                "csv_path": "core/dictionary/candidates/stock_pool_2026q1.csv",
            },
            "_comment_selection": "===== 选股输出参数 =====",
            "selection": {
                "top_n": 10,
                "min_score": 0,
            },
            "history_days": 90,
        }

    def select(self, date: str, xtdata=None,
               kline_data: pd.DataFrame = None,
               stock_list: list = None) -> BuyResult:
        """执行选股"""
        config = self.load_config()
        select_cfg = config.get('selection', {})
        top_n = select_cfg.get('top_n', 10)
        min_score = select_cfg.get('min_score', 0)

        print(f"\n{'='*60}")
        print(f"  强势整理买点选股 - {date}")
        print(f"{'='*60}")

        # 1. 股票池
        if stock_list is None:
            stock_pool = self._get_stock_pool(config)
        else:
            stock_pool = stock_list
        if not stock_pool:
            print("  [买入策略] 股票池为空")
            return BuyResult()
        print(f"  股票池: {len(stock_pool)} 只")

        # 2. K线数据
        if kline_data is not None:
            data = kline_data
        else:
            data = self._prepare_data(stock_pool, date, config)
        if data is None or data.empty:
            print("  [买入策略] 数据为空")
            return BuyResult()

        # 每只股票两段式检查
        results = self._screen_stocks(data, config, date, stock_pool)

        if not results:
            print("\n  [买入策略] 无股票通过强势熔断")
            return BuyResult()

        # 按评分排序
        sorted_items = sorted(results.items(), key=lambda x: x[1]['score'], reverse=True)

        print(f"\n  通过熔断: {len(sorted_items)} 只")
        print(f"  Top {top_n}:")

        selected = []
        prices = {}
        scores = {}

        for i, (stock, info) in enumerate(sorted_items[:top_n]):
            selected.append(stock)
            scores[stock] = info['score']
            if i < 10:
                parts = [f"评分={info['score']:.1f}"]
                for k in ['涨幅%', '量比', '缩量比', '距MA20%', '距顶天数']:
                    if k in info:
                        parts.append(f"{k}={info[k]}")
                print(f"    {i+1}. {stock}  {'  '.join(parts)}")

        prices = self._get_prices(data, date, selected)
        return BuyResult(stocks=selected, prices=prices, scores=scores, date=date)

    # ── 两段式筛选核心 ─────────────────────────────────

    def _screen_stocks(self, data: pd.DataFrame, config: dict,
                       date: str, stock_pool: list) -> dict:
        """对每只股票两段式筛选"""
        end_dt = pd.Timestamp(date)
        strong_cfg = config.get('strong_filter', {})
        score_cfg = config.get('consolidation_scoring', {})

        results = {}
        total = len(stock_pool)

        for idx, stock in enumerate(stock_pool):
            if (idx + 1) % 20 == 0:
                print(f"  进度: {idx+1}/{total}")

            try:
                sd = data.xs(stock, level='symbol').sort_index()
                sd = sd[sd.index <= end_dt]
                if len(sd) < 40:
                    continue
            except KeyError:
                continue

            # ── 第一段：强势熔断 ──
            strong_pass, sinfo = self._check_strong(sd, strong_cfg)
            if not strong_pass:
                continue

            # ── 第二段：整理评分 ──
            score, scinfo = self._score_consolidation(sd, score_cfg, sinfo)

            if score <= 0:
                continue

            results[stock] = {'score': score, **sinfo, **scinfo}

        return results

    def _check_strong(self, sd: pd.DataFrame, cfg: dict) -> tuple:
        """强势熔断检查，返回 (通过否, 信息dict)"""
        ret_days = cfg.get('return_days', 20)
        min_ret = cfg.get('min_return_pct', 15.0)
        vol_days = cfg.get('volume_days', 20)
        min_vr = cfg.get('min_volume_ratio', 1.5)
        nh_days = cfg.get('new_high_days', 20)
        nh_lookback = cfg.get('new_high_lookback', 60)

        info = {}
        n = len(sd)

        # ── 涨幅检查 ──
        if n < ret_days:
            return False, info
        start_close = sd['close'].iloc[-ret_days]
        end_close = sd['close'].iloc[-1]
        pct = (end_close / start_close - 1) * 100
        info['涨幅%'] = round(pct, 1)
        if pct < min_ret:
            return False, info

        # ── 放量检查 ──
        if n >= vol_days * 2:
            recent_vol = sd['volume'].iloc[-vol_days:].mean()
            prior_vol = sd['volume'].iloc[-(vol_days * 2):-vol_days].mean()
            if prior_vol > 0:
                vr = recent_vol / prior_vol
                info['量比'] = round(vr, 2)
                if vr < min_vr:
                    return False, info

        # ── 创过新高 ──
        if n >= nh_lookback:
            recent_high = sd['high'].iloc[-nh_days:].max()
            lookback_high = sd['high'].iloc[-nh_lookback:].max()
            info['近高/前高'] = f"{recent_high:.2f}/{lookback_high:.2f}"
            if recent_high < lookback_high:
                return False, info

        return True, info

    def _score_consolidation(self, sd: pd.DataFrame, cfg: dict, sinfo: dict) -> tuple:
        """整理质量评分 0-100"""
        vol_shrink = cfg.get('volume_shrink_pct', 0.6)
        ma_type = cfg.get('ma_support', 'MA20')
        use_obv = cfg.get('obv_divergence', True)
        use_vol = cfg.get('volatility_contraction', True)
        use_adx = cfg.get('adx_low', True)
        min_days = cfg.get('min_consolidation_days', 5)
        max_days = cfg.get('max_consolidation_days', 25)

        score = 0.0
        info = {}
        n = len(sd)

        # 均线
        closes = sd['close']
        ma20 = closes.rolling(20).mean()
        ma60 = closes.rolling(60).mean()

        ret_days = 20  # 跟强势熔断保持一致
        # 近期最高点（过去ret_days天内）
        peak_idx = sd['high'].iloc[-ret_days:].idxmax()
        peak_price = sd.loc[peak_idx, 'high']
        # 距顶天数用 loc 后的位置算
        peak_pos = sd.index.get_loc(peak_idx)
        days_since_peak = n - 1 - peak_pos

        info['距顶天数'] = days_since_peak
        retrace = (sd['close'].iloc[-1] / peak_price - 1) * 100
        sinfo['回撤%'] = round(retrace, 1)

        # ── 整理天数评分 20分 ──
        if min_days <= days_since_peak <= max_days:
            if 8 <= days_since_peak <= 15:
                score += 20
            else:
                score += 10

        # ── 缩量评分 30分 ──
        if n >= 25:
            recent_vol = sd['volume'].iloc[-5:].mean()
            pre_vol = sd['volume'].iloc[-25:-5].mean()
            if pre_vol > 0:
                sr = recent_vol / pre_vol
                info['缩量比'] = round(sr, 2)
                if sr <= vol_shrink:
                    score += 30
                elif sr <= vol_shrink * 1.3:
                    score += 20
                elif sr <= vol_shrink * 1.6:
                    score += 10
                else:
                    score += 5

        # ── 波动率收窄评分 20分 ──
        if use_vol and n >= 20:
            h = sd['high']
            l = sd['low']
            mid = (h + l) / 2
            # 真实波幅均值 ATR-like 带宽
            bandwidth = (h.rolling(20).max() - l.rolling(20).min()) / mid.rolling(20).mean() * 100
            recent_bw = bandwidth.iloc[-5:].mean()
            past_bw = bandwidth.iloc[-20:-5].mean()
            if pd.notna(recent_bw) and pd.notna(past_bw) and past_bw > 0:
                wr = recent_bw / past_bw
                info['波动比'] = round(wr, 2)
                if wr <= 0.5:
                    score += 20
                elif wr <= 0.7:
                    score += 15
                elif wr <= 0.85:
                    score += 10
                else:
                    score += 5

        # ── 均线支撑评分 15分 ──
        cur_close = sd['close'].iloc[-1]
        if ma_type in ('MA20', 'BOTH'):
            mv = ma20.iloc[-1]
            if pd.notna(mv):
                dist = abs(cur_close / mv - 1) * 100
                info['距MA20%'] = round(dist, 2)
                if dist <= 2:
                    score += 15 if ma_type == 'MA20' else 8
                elif dist <= 5:
                    score += 8 if ma_type == 'MA20' else 4
        if ma_type in ('MA60', 'BOTH'):
            mv = ma60.iloc[-1]
            if pd.notna(mv):
                dist = abs(cur_close / mv - 1) * 100
                info['距MA60%'] = round(dist, 2)
                if dist <= 2:
                    score += 7
                elif dist <= 5:
                    score += 4

        # ── OBV 背离评分 10分 ──
        if use_obv and n >= 30:
            obv = self._obv(sd.iloc[-30:])
            obv_recent_low = obv.iloc[-10:].min()
            obv_past_low = obv.iloc[:10].min()
            price_low = sd['close'].iloc[-30:].min()
            cur_price = sd['close'].iloc[-1]
            if obv_recent_low >= obv_past_low and cur_price <= price_low * 1.1:
                score += 10
                info['OBV'] = '背离✓'

        # ── ADX 评分 5分 ──
        if use_adx and n >= 25:
            adx = self._adx(sd.iloc[-25:])
            if not adx.empty:
                recent_adx = adx.iloc[-5:].mean()
                info['ADX'] = round(recent_adx, 1) if pd.notna(recent_adx) else 0
                if pd.notna(recent_adx):
                    if recent_adx < 25:
                        score += 5

        score = min(score, 100)
        info['total_score'] = round(score, 1)
        return score, info

    # ── 技术指标 ─────────────────────────────────────

    def _obv(self, data: pd.DataFrame) -> pd.Series:
        """能量潮 OBV"""
        direction = (~(data['close'].diff() < 0)).astype(int) * 2 - 1
        direction.iloc[0] = 0
        return (data['volume'] * direction).cumsum()

    def _adx(self, data: pd.DataFrame) -> pd.Series:
        """平均趋向指数 ADX(14)"""
        high, low, close = data['high'], data['low'], data['close']
        prev_close = close.shift(1)

        # 真实波幅 TR
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        # 方向移动
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(0.0, index=data.index)
        minus_dm = pd.Series(0.0, index=data.index)
        mask_up = (up > down) & (up > 0)
        mask_down = (down > up) & (down > 0)
        plus_dm[mask_up] = up[mask_up]
        minus_dm[mask_down] = down[mask_down]

        w = 14
        tr_s = tr.rolling(w).mean()
        pdi = 100 * plus_dm.rolling(w).mean() / tr_s.replace(0, np.nan)
        mdi = 100 * minus_dm.rolling(w).mean() / tr_s.replace(0, np.nan)
        dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
        return dx.rolling(w).mean()

    # ── 数据加载（同因子策略） ─────────────────────────

    def _get_stock_pool(self, config: dict) -> list:
        """获取股票池"""
        pool_cfg = config.get('stock_pool', {})
        source = pool_cfg.get('source', 'csv')

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
        history_days = config.get('history_days', 90)
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=history_days * 2)
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

    def _get_prices(self, data: pd.DataFrame, date: str, stocks: list) -> dict:
        """获取指定日期的收盘价"""
        prices = {}
        target = pd.Timestamp(date)
        try:
            date_data = data.xs(target, level='date', drop_level=False)
            for s in stocks:
                try:
                    p = date_data.loc[(target, s), 'close']
                    prices[s] = float(p)
                except (KeyError, TypeError):
                    continue
        except Exception:
            pass
        return prices
