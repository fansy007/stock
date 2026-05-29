"""
核心函数：build_profile() — 生成全 A 股 5 年财务+K线宽表。

每次跑完缓存 parquet，增量更新或固定参数再跑时读缓存。
"""

import pandas as pd
import numpy as np
import json
import os
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]      # stock/
EXPORT_DATA = BASE_DIR / "export" / "data"
DICT_DIR = BASE_DIR / "core" / "dictionary"
KLINE_DIR = EXPORT_DATA / "kline"

CACHE_PATH = DICT_DIR / "stock_profile.parquet"
META_PATH = DICT_DIR / "stock_profile_meta.json"
N = 5  # 5 年

INCOME_COLS = [
    "stock_code", "m_timetag",
    "revenue",
    "net_profit_excl_min_int_inc",
    "oper_profit", "financial_expense",
]
CASHFLOW_COLS = [
    "stock_code", "m_timetag",
    "net_cash_flows_oper_act",
]
BALANCE_COLS = [
    "stock_code", "m_timetag",
    "account_receivable", "inventories", "accounts_payable",
    "tot_assets", "tot_liab", "total_equity", "goodwill",
    "advance_payment",
]


# ── 工具 ─────────────────────────────────────────────

def _to_yi(s):
    """元 → 亿元"""
    return s / 1e8 if s.notna().any() else s


def _read_csv_cols(path, cols):
    with open(path, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    use = [c for c in cols if c in header]
    return pd.read_csv(path, usecols=use, encoding="utf-8"), use


def _pivot_annual(df, value_col, name, years):
    """将年度的 stock_code×year 宽表化。"""
    p = df.pivot_table(index="stock_code", columns="year",
                       values=value_col, aggfunc="first")
    for y in years:
        if y not in p.columns:
            p[y] = np.nan
    p = p[years]
    p.columns = [f"{name}_{int(y)}" for y in years]
    return p


# ── 加载基础信息 ─────────────────────────────────────

def _load_basic():
    with open(DICT_DIR / "stock_profile.json") as f:
        raw = json.load(f)
    rows = []
    for code, info in raw.items():
        rows.append({
            "stock_code": code,
            "name": info.get("name", ""),
            "SW1": info.get("SW1"),
            "SW2": info.get("SW2"),
            "concepts": ",".join(info.get("concepts", [])),
        })
    return pd.DataFrame(rows)


# ── 年度指标（5年） ──────────────────────────────────

def _calc_annual():
    t0 = time.time()

    inc, _ = _read_csv_cols(EXPORT_DATA / "Income.csv", INCOME_COLS)
    cf, _ = _read_csv_cols(EXPORT_DATA / "CashFlow.csv", CASHFLOW_COLS)
    bal, _ = _read_csv_cols(EXPORT_DATA / "Balance.csv", BALANCE_COLS)

    for d in [inc, cf, bal]:
        d["_t"] = d["m_timetag"].astype(str)
        d["year"] = d["_t"].str[:4].astype(int)

    # 只取年报 (1231)
    inc_a = inc[inc["_t"].str.endswith("1231")].copy()
    cf_a = cf[cf["_t"].str.endswith("1231")].copy()
    bal_a = bal[bal["_t"].str.endswith("1231")].copy()

    years = sorted(inc_a["year"].unique(), reverse=True)[:N]
    years.sort()  # [2021, 2022, 2023, 2024, 2025]

    # ── 构建各指标宽表 ──
    rev_w = _pivot_annual(inc_a, "revenue", "rev", years)
    np_w = _pivot_annual(inc_a, "net_profit_excl_min_int_inc", "np", years)
    oper_w = _pivot_annual(inc_a, "oper_profit", "_oper", years)
    fin_exp_w = _pivot_annual(inc_a, "financial_expense", "_finexp", years)

    ocf_w = _pivot_annual(cf_a, "net_cash_flows_oper_act", "ocf", years)

    ar_w = _pivot_annual(bal_a, "account_receivable", "_ar", years)
    inv_w = _pivot_annual(bal_a, "inventories", "_inv", years)
    ap_w = _pivot_annual(bal_a, "accounts_payable", "ap", years)
    adv_w = _pivot_annual(bal_a, "advance_payment", "_advance", years)
    ta_w = _pivot_annual(bal_a, "tot_assets", "_ta", years)
    tl_w = _pivot_annual(bal_a, "tot_liab", "_tl", years)
    eq_w = _pivot_annual(bal_a, "total_equity", "_eq", years)
    gw_w = _pivot_annual(bal_a, "goodwill", "_gw", years)

    # ── 合并 ──
    result = rev_w.join(np_w).join(oper_w).join(fin_exp_w) \
                  .join(ocf_w).join(ar_w).join(inv_w).join(ap_w) \
                  .join(adv_w) \
                  .join(ta_w).join(tl_w).join(eq_w).join(gw_w)
    result.reset_index(inplace=True)

    # 单位换算 元→亿元
    for pfx in ["rev_", "np_", "ocf_", "ap_", "_ar_", "_inv_", "_advance_",
                "_oper_", "_finexp_", "_ta_", "_tl_", "_eq_", "_gw_"]:
        for c in [col for col in result.columns if col.startswith(pfx)]:
            result[c] = _to_yi(result[c])

    # ── 计算衍生指标 ──
    # 营业利润率 = oper_profit / revenue
    for y in years:
        r, o = f"rev_{y}", f"_oper_{y}"
        om = f"om_{y}"
        result[om] = np.nan
        mask = result[r].notna() & (result[r] > 0) & result[o].notna()
        result.loc[mask, om] = (result.loc[mask, o] / result.loc[mask, r] * 100).round(2)

    # ROE = np / equity
    for y in years:
        result[f"roe_{y}"] = (result[f"np_{y}"] / result[f"_eq_{y}"] * 100).round(2)

    # 应收、存货、应付、预付单独
    for y in years:
        result[f"ar_inv_{y}"] = (result[f"_ar_{y}"] + result[f"_inv_{y}"]).round(2)
        result[f"ar_{y}"] = result[f"_ar_{y}"].round(2)
        result[f"inv_{y}"] = result[f"_inv_{y}"].round(2)
        result[f"advance_{y}"] = result[f"_advance_{y}"].round(2)
        result[f"ar_inv_prep_{y}"] = (result[f"_ar_{y}"] + result[f"_inv_{y}"] + result[f"_advance_{y}"]).round(2)

    # ── 同比增长 ──
    for i in range(1, len(years)):
        cy = years[i]
        py = years[i - 1]

        # 增速  (cy - py) / |py|
        for pfx in ["rev_", "np_", "ocf_", "ap_", "ar_inv_", "ar_", "inv_",
                     "advance_", "ar_inv_prep_"]:
            prev = result[f"{pfx}{py}"]
            cur = result[f"{pfx}{cy}"]
            result[f"{pfx}gr_{cy}"] = ((cur - prev) / prev.abs() * 100).round(2)

        # 营业利润率变化 (百分点)
        result[f"om_chg_{cy}"] = (result[f"om_{cy}"] - result[f"om_{py}"]).round(2)

    t1 = time.time()
    print(f"[profile] 年度指标计算完成 {len(result)} 行, {t1-t0:.1f}s")
    return result


# ── 最新季度同比 ─────────────────────────────────────

def _calc_latest_quarter():
    inc, _ = _read_csv_cols(EXPORT_DATA / "Income.csv", INCOME_COLS)
    inc["_t"] = inc["m_timetag"].astype(str)
    inc["year"] = inc["_t"].str[:4].astype(int)

    # 找出最新非年报季度
    q = inc[~inc["_t"].str.endswith("1231")].copy()
    if q.empty:
        return pd.DataFrame({"stock_code": []})

    latest_tag = q["_t"].max()
    latest_year = int(latest_tag[:4])
    latest_q = latest_tag[4:]  # 0331 / 0630 / 0930
    same_q_last = f"{latest_year-1}{latest_q}"

    # 取最新季度 和 去年同期的数据
    cur = q[q["_t"] == latest_tag].copy()
    prev = inc[inc["_t"] == same_q_last].copy()

    # 如果当前季度是 0331 (Q1), 单季值 = 原始值（累计即当季）
    # 如果是 0630 (H1), Q2 单季 = 累计 - Q1
    def _single_q_val(df, tag):
        """估算单季值。"""
        q_type = tag[4:]
        if q_type == "0331":
            return df
        # 需要减去上一累计值才能得到本季
        q1_tag = f"{tag[:4]}0331"
        df_q1 = inc[inc["_t"] == q1_tag]
        merged = df.merge(df_q1, on="stock_code", suffixes=("", "_q1"), how="left")
        for col in ["revenue", "net_profit_excl_min_int_inc"]:
            q1_val = merged.get(f"{col}_q1", np.nan)
            if q1_val is not None:
                merged[col] = merged[col] - q1_val.fillna(0)
        return merged

    cur_sq = _single_q_val(cur, latest_tag)
    prev_sq = _single_q_val(prev, same_q_last)

    # 合并
    cur_sq = cur_sq[["stock_code", "revenue",
                      "net_profit_excl_min_int_inc"]].copy()
    prev_sq = prev_sq[["stock_code", "revenue",
                        "net_profit_excl_min_int_inc"]].copy()

    cur_sq.columns = ["stock_code", "q_rev", "q_np"]
    prev_sq.columns = ["stock_code", "p_rev", "p_np"]

    result = cur_sq.merge(prev_sq, on="stock_code", how="left")

    # 单位换算
    for c in ["q_rev", "q_np", "p_rev", "p_np"]:
        result[c] = _to_yi(result[c])

    # 最新季度同比
    result["q_rev_yoy"] = _calc_growth(result["q_rev"], result["p_rev"])
    result["q_np_yoy"] = _calc_growth(result["q_np"], result["p_np"])

    result.drop(columns=["p_rev", "p_np"], inplace=True)

    # ── 资产负债表季度数据 ──
    bal, _ = _read_csv_cols(EXPORT_DATA / "Balance.csv", BALANCE_COLS)
    bal["_t"] = bal["m_timetag"].astype(str)
    bq = bal[~bal["_t"].str.endswith("1231")].copy()
    if not bq.empty:
        blatest_tag = bq["_t"].max()
        blatest_year = int(blatest_tag[:4])
        blatest_q = blatest_tag[4:]
        bcur = bq[bq["_t"] == blatest_tag][
            ["stock_code", "account_receivable", "inventories", "accounts_payable",
             "advance_payment"]
        ].copy()
        bprev = bal[bal["_t"] == f"{blatest_year-1}{blatest_q}"][
            ["stock_code", "account_receivable", "inventories", "accounts_payable",
             "advance_payment"]
        ].copy()
        bcur.columns = ["stock_code", "q_ar", "q_inv", "q_ap", "q_advance"]
        bprev.columns = ["stock_code", "p_ar", "p_inv", "p_ap", "p_advance"]
        bres = bcur.merge(bprev, on="stock_code", how="left")
        for c in ["q_ar", "q_inv", "q_ap", "q_advance",
                   "p_ar", "p_inv", "p_ap", "p_advance"]:
            bres[c] = _to_yi(bres[c])
        for col in ["ar", "inv", "ap", "advance"]:
            bres[f"q_{col}_yoy"] = _calc_growth(bres[f"q_{col}"], bres[f"p_{col}"])
        bres.drop(columns=["p_ar", "p_inv", "p_ap", "p_advance"], inplace=True)
        result = result.merge(bres, on="stock_code", how="left")

    return result


def _calc_growth(cur, prev):
    g = (cur - prev) / prev.abs() * 100
    return g.round(2)


# ── K线收益率 ────────────────────────────────────────

RET_WINDOWS = {
    "1w": 5, "1m": 21, "3m": 63, "6m": 126,
    "1y": 252, "2y": 504, "3y": 756, "5y": 1260,
}

def _calc_returns():
    t0 = time.time()
    rows = []
    files = sorted(KLINE_DIR.glob("*.csv"))
    n = len(files)
    for i, f in enumerate(files):
        code = f.stem
        try:
            close = pd.read_csv(f, usecols=["close"]).squeeze("columns").values
        except Exception:
            rows.append({"stock_code": code, **{f"ret_{k}": np.nan for k in RET_WINDOWS}})
            continue
        latest = close[-1]
        r = {"stock_code": code}
        for name, lookback in RET_WINDOWS.items():
            if len(close) > lookback:
                r[f"ret_{name}"] = round((latest / close[-1-lookback] - 1) * 100, 2)
            else:
                r[f"ret_{name}"] = np.nan
        rows.append(r)
        if (i + 1) % 1000 == 0:
            print(f"[profile] K线收益率 {i+1}/{n}")

    result = pd.DataFrame(rows)
    print(f"[profile] K线收益率计算完成 {n} 只, {time.time()-t0:.1f}s")
    return result


# ── 安全指标（取最新年）───────────────────────────────

def _add_safety_metrics(df):
    """计算最新一年的安全类指标（一次性添加所有列）。"""
    years = sorted([int(c.split("_")[-1]) for c in df.columns
                    if c.startswith("rev_") and c.split("_")[-1].isdigit()])
    if not years:
        return df

    ly = years[-1]
    safe = pd.DataFrame(index=df.index)
    safe["stock_code"] = df["stock_code"]

    tl_col, ta_col = f"_tl_{ly}", f"_ta_{ly}"
    eq_col, gw_col = f"_eq_{ly}", f"_gw_{ly}"
    rev_col = f"rev_{ly}"
    ar_col, inv_col, adv_col = f"_ar_{ly}", f"_inv_{ly}", f"_advance_{ly}"
    oper_col, finexp_col = f"_oper_{ly}", f"_finexp_{ly}"
    np_col, ocf_col = f"np_{ly}", f"ocf_{ly}"

    # 资产负债率
    safe["debt_ratio"] = (df[tl_col] / df[ta_col] * 100).round(2)

    # 利息覆盖
    safe["int_cvg"] = np.nan
    mask = df[finexp_col].notna() & (df[finexp_col] > 0)
    safe.loc[mask, "int_cvg"] = (df.loc[mask, oper_col] / df.loc[mask, finexp_col]).round(2)

    # 应收+存货+预付/营收（预付NaN视为0）
    _adv = df[adv_col].fillna(0)
    safe["ar_inv_prep_to_rev"] = (
        (df[ar_col] + df[inv_col] + _adv) / df[rev_col] * 100
    ).round(2)

    # 商誉/净资产
    safe["gw_ratio"] = np.nan
    mask = df[eq_col].notna() & (df[eq_col] != 0)
    safe.loc[mask, "gw_ratio"] = (df.loc[mask, gw_col] / df.loc[mask, eq_col] * 100).round(2)

    # cf_to_np（净利>0时正常算，<=0时空）
    safe["cf_to_np"] = np.nan
    mask = df[np_col].notna() & (df[np_col] > 0)
    safe.loc[mask, "cf_to_np"] = (df.loc[mask, ocf_col] / df.loc[mask, np_col]).round(2)

    # 删中间列，合并安全指标
    drop = [c for c in df.columns if c.startswith("_")]
    df.drop(columns=drop, inplace=True)

    # 去掉 safe 中已有的 stock_code 避免重复
    safe.drop(columns=["stock_code"], inplace=True)
    return pd.concat([df, safe], axis=1)


# ── 对外接口 ─────────────────────────────────────────

def build_profile(refresh=False):
    """生成全 A 股 5 年财务+K线宽表。

    返回 DataFrame (5207 行 × ~80 列)，同时缓存 parquet。
    refresh=True 时强制重新计算。
    """
    if not refresh and CACHE_PATH.exists():
        t0 = time.time()
        df = pd.read_parquet(CACHE_PATH)
        print(f"[profile] 读取缓存 {CACHE_PATH.name} ({len(df)} 行, {time.time()-t0:.1f}s)")
        print(f"[profile] 缓存时间: {_get_cache_meta().get('built_at', 'unknown')}")
        return df

    t0 = time.time()
    print("[profile] 重新计算全量数据...")

    basic = _load_basic()
    annual = _calc_annual().drop_duplicates(subset="stock_code")
    quarter = _calc_latest_quarter().drop_duplicates(subset="stock_code")
    returns = _calc_returns().drop_duplicates(subset="stock_code")

    df = (basic.merge(annual, on="stock_code", how="left")
               .merge(quarter, on="stock_code", how="left")
               .merge(returns, on="stock_code", how="left"))
    df = _add_safety_metrics(df)

    # 最后清理中间列
    drop = [c for c in df.columns if c.startswith("_")]
    if drop:
        df.drop(columns=drop, inplace=True)

    # 缓存
    df.to_parquet(CACHE_PATH, index=False)
    meta = {
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": len(df),
        "cols": len(df.columns),
        "build_time_s": round(time.time() - t0, 1),
        "latest_annual": "latest_1231",
        "latest_quarter": "latest_non_1231",
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[profile] 完成 {len(df)} 行 × {len(df.columns)} 列, {time.time()-t0:.1f}s")
    return df


def _get_cache_meta():
    try:
        with open(META_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def cache_info():
    """打印缓存元信息。"""
    return _get_cache_meta()
