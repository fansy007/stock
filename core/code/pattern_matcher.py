"""
形态匹配模块。

用最近 N 天走势（归一化收盘价 + 成交量）匹配历史相似窗口，
统计后续 M 天的走势分布，作为交易决策的情景参考。

用法:
    from core.code.pattern_matcher import PatternMatcher

    pm = PatternMatcher()
    result = pm.match("300990.SZ", window=20, top_k=5, lookahead=10)

    # 直接打印报告
    pm.report(result)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class MatchSegment:
    """一段匹配结果"""
    rank: int                    # 相似度排名 1~K
    start_date: str              # 匹配窗口起始日期
    end_date: str                # 匹配窗口结束日期
    corr_close: float            # 收盘价相关系数
    corr_volume: float           # 成交量相关系数
    match_norm_close: list       # 匹配段的归一化收盘价
    after_dates: list            # 后续交易日日期
    after_close: list            # 后续交易日收盘价
    after_return: float          # lookahead 天后的涨跌幅 (%)
    after_high: float            # lookahead 期间最高涨幅 (%)
    after_low: float             # lookahead 期间最低涨幅 (%)


@dataclass
class MatchResult:
    """形态匹配的完整结果"""
    code: str                    # 股票代码
    name: str                    # 股票名称（如有）
    window: int                  # 匹配窗口天数
    top_k: int                   # 返回的匹配段数
    lookahead: int               # 后续观察天数
    current_dates: list          # 当前窗口日期
    current_close: list          # 当前窗口收盘价
    current_volume: list         # 当前窗口成交量
    current_norm_close: list     # 当前窗口归一化收盘价
    matches: list                # 匹配段列表（MatchSegment）
    stats: dict = field(default_factory=dict)  # 统计汇总


class PatternMatcher:
    """形态匹配引擎"""

    def __init__(self, kline_dir: str = "export/data/kline"):
        self.kline_dir = Path(kline_dir)
        # 名称映射（从 profile 加载）
        self._name_map: dict[str, str] = {}

    def load_name_map(self, profile_df) -> None:
        """从 build_profile() 的 DataFrame 加载 code→name 映射"""
        for _, r in profile_df.iterrows():
            self._name_map[r["stock_code"]] = r["name"]

    # ---- 主入口 ----

    def match(
        self,
        code: str,
        window: int = 20,
        top_k: int = 5,
        lookahead: int = 10,
        period: str = "1y",
        min_corr: float = 0.7,
    ) -> Optional[MatchResult]:
        """
        形态匹配主函数。

        参数:
            code: 股票代码，如 "300990.SZ"
            window: 匹配窗口天数
            top_k: 返回最相似的段数
            lookahead: 匹配后观察多少天
            period: 历史回溯周期 ("1y"/"2y"/"all")
            min_corr: 最小相关系数门槛

        返回:
            MatchResult or None（数据不足时）
        """
        kline = self._load_kline(code)
        if kline is None or len(kline) < window + lookahead + 20:
            return None

        # 确定回溯长度
        n_days = {"1y": 250, "2y": 500, "all": len(kline)}.get(period, 250)
        hist = kline.iloc[-(n_days + window + lookahead):].reset_index(drop=True)

        # 当前窗口（最后 window 天）
        current = kline.iloc[-window:].reset_index(drop=True)
        cur_close = current["close"].values / current["close"].iloc[0]
        cur_vol = current["volume"].values / current["volume"].mean()

        # 滑动匹配
        segments = []
        max_start = len(hist) - window - lookahead
        for i in range(max_start):
            seg = hist.iloc[i:i + window]
            seg_close = seg["close"].values / seg["close"].iloc[0]

            # 跳过所有 NaN 段
            if np.any(np.isnan(seg_close)) or np.any(np.isnan(cur_close)):
                continue

            # 收盘价相关系数
            corr_c = np.corrcoef(seg_close, cur_close)[0, 1]
            if np.isnan(corr_c) or corr_c < min_corr:
                continue

            # 成交量相关系数
            seg_vol = seg["volume"].values / seg["volume"].mean()
            corr_v = np.corrcoef(seg_vol, cur_vol)[0, 1]
            corr_v = 0 if np.isnan(corr_v) else corr_v

            # 综合得分：收盘价形态权重0.7，成交量0.3
            score = 0.7 * corr_c + 0.3 * corr_v

            # 后续走势
            after = hist.iloc[i + window:i + window + lookahead]
            after_close = after["close"].values
            base_price = seg["close"].iloc[-1]
            after_rets = (after_close / base_price - 1) * 100

            segments.append({
                "start": str(seg["date"].iloc[0].date()),
                "end": str(seg["date"].iloc[-1].date()),
                "corr_c": round(corr_c, 4),
                "corr_v": round(corr_v, 4),
                "score": round(score, 4),
                "norm_close": [round(float(x), 4) for x in seg_close],
                "after_dates": [str(d.date()) for d in after["date"]],
                "after_close": [round(float(x), 2) for x in after_close],
                "after_return": round(after_rets[-1], 2) if len(after_rets) > 0 else None,
                "after_high": round(float(after_rets.max()), 2) if len(after_rets) > 0 else None,
                "after_low": round(float(after_rets.min()), 2) if len(after_rets) > 0 else None,
            })

        if not segments:
            return None

        # 按综合得分排序
        segments.sort(key=lambda x: x["score"], reverse=True)

        # 去重：排除重叠窗口（起始日相差 < window 天视为重叠）
        selected = []
        occupied = set()
        for seg in segments:
            seg_start_idx = int(pd.Timestamp(seg["start"]).timestamp())
            # 检查是否与已选段重叠
            overlap = False
            for occ_start, occ_end in occupied:
                if not (seg_start_idx >= occ_end or seg_start_idx + window * 86400 <= occ_start):
                    overlap = True
                    break
            if not overlap:
                occupied.add((seg_start_idx, seg_start_idx + window * 86400))
                selected.append(seg)
                if len(selected) >= top_k:
                    break

        # 构造结果
        matches = []
        for i, seg in enumerate(selected):
            matches.append(MatchSegment(
                rank=i + 1,
                start_date=seg["start"],
                end_date=seg["end"],
                corr_close=seg["corr_c"],
                corr_volume=seg["corr_v"],
                match_norm_close=seg["norm_close"],
                after_dates=seg["after_dates"],
                after_close=seg["after_close"],
                after_return=seg["after_return"],
                after_high=seg["after_high"],
                after_low=seg["after_low"],
            ))

        returns = [m.after_return for m in matches if m.after_return is not None]
        stats = {}
        if returns:
            stats = {
                "win_rate": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
                "median_return": round(float(np.median(returns)), 2),
                "mean_return": round(float(np.mean(returns)), 2),
                "max_return": max(returns),
                "min_return": min(returns),
                "positive_count": sum(1 for r in returns if r > 0),
                "negative_count": sum(1 for r in returns if r <= 0),
                "total_count": len(returns),
            }

        name = self._name_map.get(code, "")

        return MatchResult(
            code=code,
            name=name,
            window=window,
            top_k=top_k,
            lookahead=lookahead,
            current_dates=[str(d.date()) for d in current["date"]],
            current_close=[round(float(x), 2) for x in current["close"]],
            current_volume=[int(x) for x in current["volume"]],
            current_norm_close=[round(float(x), 4) for x in cur_close],
            matches=matches,
            stats=stats,
        )

    # ---- 报告输出 ----

    def report(self, result: MatchResult) -> str:
        """生成可读的文本报告"""
        if result is None:
            return "数据不足，无法匹配。"

        name_tag = f" ({result.name})" if result.name else ""
        lines = [
            f"{result.code}{name_tag} | 窗口={result.window}天 | 匹配={result.top_k}段 | 看后{result.lookahead}天",
            "",
        ]

        # 当前走势
        cur = result.current_norm_close
        if cur:
            arrow = "→".join(
                f"{v:.2f}" if i % 5 != 0 else f"{v:.2f}"
                for i, v in enumerate(cur)
            )
            lines.append(f"当前归一化: {cur[0]:.2f} → {cur[-1]:.2f} ({((cur[-1]/cur[0]-1)*100):.1f}%)")

        lines.append("")

        # 每段匹配
        for m in result.matches:
            ret = m.after_return
            ret_str = f"{ret:+.2f}%" if ret is not None else "N/A"
            lines.append(
                f"  #{m.rank} | {m.start_date}~{m.end_date} | "
                f"形态相关={m.corr_close:.3f} 量相关={m.corr_volume:.3f} | "
                f"后{result.lookahead}天: {ret_str} "
                f"(高:{m.after_high:+.1f}% 低:{m.after_low:+.1f}%)"
            )

        # 统计
        s = result.stats
        if s:
            lines.extend([
                "",
                f"  统计: 胜率{s['win_rate']}% ({s['positive_count']}/{s['total_count']}) | "
                f"中位数{s['median_return']:+.2f}% | "
                f"均值{s['mean_return']:+.2f}% | "
                f"范围{s['min_return']:+.1f}%~{s['max_return']:+.1f}%",
            ])

        return "\n".join(lines)

    def to_dict(self, result: MatchResult) -> dict:
        """转为 dict，便于 GUI 调用"""
        return {
            "code": result.code,
            "name": result.name,
            "window": result.window,
            "top_k": result.top_k,
            "lookahead": result.lookahead,
            "current": {
                "dates": result.current_dates,
                "close": result.current_close,
                "volume": result.current_volume,
                "norm_close": result.current_norm_close,
            },
            "matches": [asdict(m) for m in result.matches],
            "stats": result.stats,
        }

    # ---- 内部 ----

    def _load_kline(self, code: str) -> Optional[pd.DataFrame]:
        """加载个股K线，返回 date(升序) close volume 三列"""
        fp = self.kline_dir / f"{code}.csv"
        if not fp.exists():
            return None
        try:
            df = pd.read_csv(fp)
            df["date"] = pd.to_datetime(df["time"], unit="ms")
            df = df[df["close"].notna() & (df["close"] > 0)].copy()
            df = df.sort_values("date").reset_index(drop=True)
            return df[["date", "close", "volume"]]
        except Exception:
            return None
