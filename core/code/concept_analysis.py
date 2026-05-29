"""
概念分析工具：分析一个同花顺概念的内部结构。

用法:
    from core.code.concept_analysis import concept_report
    concept_report("PCB概念")
    concept_report("低空经济", top_n=15)
"""

import pandas as pd
import numpy as np

BASE = "/Users/hg26502/claude/stock"


def concept_report(concept_name: str, top_n: int = 10):
    """打印一个概念的分析报告。"""
    df = pd.read_parquet(f"{BASE}/core/dictionary/stock_profile.parquet")

    # 匹配概念（用 regex=False 避免特殊字符报错）
    mask = df["concepts"].str.contains(concept_name, na=False, regex=False)
    group = df[mask].copy()
    if group.empty:
        print(f"概念「{concept_name}」没有匹配到任何股票")
        return

    print(f"{'='*70}")
    print(f"  {concept_name} — {len(group)} 只股票")
    print(f"{'='*70}")

    # ── 板块总览 ──
    print(f"\n▎板块总览 (中位数)")
    print(f"  {'指标':<20} {'年报2025':>10} {'Q1 2026':>10} {'2025年报':>10}")
    print(f"  {'─'*50}")
    for label, col_a, col_q in [
        ("营收增速", "rev_gr_2025", "q_rev_yoy"),
        ("净利增速", "np_gr_2025", "q_np_yoy"),
    ]:
        a = group[col_a].median()
        q = group[col_q].median()
        print(f"  {label:<20} {f'{a:.1f}%':>10} {f'{q:.1f}%':>10}")

    om = group["om_2025"].median()
    roe = group["roe_2025"].median()
    debt = group["debt_ratio"].median()
    print(f"  {'营业利润率':<20} {f'{om:.1f}%':>10}")
    print(f"  {'ROE':<20} {f'{roe:.1f}%':>10}")
    print(f"  {'负债率':<20} {f'{debt:.1f}%':>10}")

    # 涨幅
    for lbl, col in [("近1周", "ret_1w"), ("近1月", "ret_1m"),
                     ("近3月", "ret_3m"), ("近6月", "ret_6m"),
                     ("近1年", "ret_1y")]:
        v = group[col].median()
        print(f"  {f'涨幅{lbl}':<20} {f'{v:.1f}%':>10}")

    # 退出率
    gw_risk = (group["gw_ratio"] > 20).mean() * 100
    debt_risk = (group["debt_ratio"] > 70).mean() * 100
    loss = (group["np_2025"] < 0).mean() * 100
    score = group["score"].median()
    green = (group["status"] == "绿灯").mean() * 100

    print(f"\n  {'评分中位数':<20} {f'{score:.1f}':>10}")
    print(f"  {'绿灯率':<20} {f'{green:.0f}%':>10}")
    print(f"  {'亏损占比':<20} {f'{loss:.0f}%':>10}")
    print(f"  {'高商誉(>20%)':<20} {f'{gw_risk:.0f}%':>10}")
    print(f"  {'高负债(>70%)':<20} {f'{debt_risk:.0f}%':>10}")

    # ── 行业构成 ──
    print(f"\n▎行业构成 (SW1, >5%的)")
    sw1_dist = group["SW1"].value_counts()
    total = len(group)
    for ind, cnt in sw1_dist.items():
        pct = cnt / total * 100
        if pct >= 5:
            sub = group[group["SW1"] == ind]
            print(f"  {ind:<14} {cnt:>4} 只 ({pct:.0f}%)  "
                  f"增速{sub['q_rev_yoy'].median():.1f}% | "
                  f"涨幅{sub['ret_1y'].median():.1f}%")

    # ── 龙头列表（按营收规模排序） ──
    print(f"\n▎龙头 TOP{top_n}（按营收规模）")
    print(f"  {'#':<3} {'名称':<12} {'SW2':<12} "
          f"{'营收':>8} {'营收增速':>10} {'Q1营收增速':>10} {'净利':>8} "
          f"{'OM%':>6} {'ROE%':>6} {'涨幅1Y':>8} {'涨幅3M':>8} {'评分':>5}")
    print(f"  {'─'*95}")

    top = group.nlargest(top_n, "rev_2025")
    for i, (_, r) in enumerate(top.iterrows(), 1):
        name = r["name"][:10]
        print(f"  {i:<3} {name:<12} {str(r['SW2'])[:10]:<12} "
              f"{r['rev_2025']:>8.0f} "
              f"{r['rev_gr_2025']:>+9.1f}% "
              f"{r['q_rev_yoy'] if pd.notna(r['q_rev_yoy']) else 'N/A':>9}"
              f"{r['np_2025']:>8.1f} "
              f"{r['om_2025']:>5.1f}% "
              f"{r['roe_2025']:>5.1f}% "
              f"{r['ret_1y']:>+7.1f}% "
              f"{r['ret_3m']:>+7.1f}% "
              f"{r['score']:>5.1f}")

    # ── 涨幅 vs 业绩匹配 ──
    print(f"\n▎涨幅 vs 业绩匹配")
    # 四象限：高增长低涨幅 = 背离
    rev_med = group["q_rev_yoy"].median()
    ret_med = group["ret_1y"].median()

    # 背离组：Q1营收增速 > 板块中位数 且 1年涨幅 < 板块中位数
    divergence = group[
        (group["q_rev_yoy"] > rev_med)
        & (group["ret_1y"] < ret_med)
        & (group["q_rev_yoy"].notna())
    ].sort_values("q_rev_yoy", ascending=False)

    print(f"  板块营收增速中位数: {rev_med:.1f}%")
    print(f"  板块涨幅中位数: {ret_med:.1f}%")
    print(f"  ⚡ 背离（高增长+低涨幅）: {len(divergence)} 只")
    if len(divergence) > 0:
        print(f"  {'名称':<12} {'SW2':<12} {'营收':>8} {'Q1增速':>8} {'年报增速':>8} {'涨幅1Y':>8} {'涨幅3M':>8} {'评分':>5}")
        print(f"  {'─'*65}")
        for _, r in divergence.head(10).iterrows():
            print(f"  {r['name'][:10]:<12} {str(r['SW2'])[:10]:<12} "
                  f"{r['rev_2025']:>8.0f} "
                  f"{r['q_rev_yoy']:>+7.1f}% "
                  f"{r['rev_gr_2025']:>+7.1f}% "
                  f"{r['ret_1y']:>+7.1f}% "
                  f"{r['ret_3m']:>+7.1f}% "
                  f"{r['score']:>5.1f}")

    print()
