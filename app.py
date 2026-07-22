"""
A 股浏览器 — 5207 只股票的大表快速过滤。

用法:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import json
from pathlib import Path

# 回测页面组件
from code.backtest.web import render_backtest_page
from core.code.predictions.web import render_predictions
from core.code.portfolio.web import render_portfolio
from core.code.candidates.db import (
    create_candidate, get_candidate_by_code, list_candidates,
    update_candidate, delete_candidate, list_tags,
)

# JSON 编辑器
from streamlit_ace import st_ace

BASE = Path(__file__).parent
CACHE_PATH = BASE / "core" / "dictionary" / "stock_profile.parquet"

# ── 列名中文映射 ───────────────────────────────────

COL_CN = {
    "stock_code": "代码", "name": "名称", "SW1": "申万一级行业",
    "SW2": "申万二级行业", "concepts": "概念", "status": "状态",
    "score": "评分", "score_A": "A盈利质量", "score_B": "B现金流安全",
    "score_C": "C资产质量", "score_D": "D破绽",
}

_yrs = [2021, 2022, 2023, 2024, 2025]
for y in _yrs:
    COL_CN.update({
        f"rev_{y}": f"营收_{y}(亿)", f"np_{y}": f"净利_{y}(亿)",
        f"om_{y}": f"营业利润率_{y}%", f"roe_{y}": f"ROE_{y}%",
        f"ocf_{y}": f"经营现金流_{y}(亿)",
        f"ar_{y}": f"应收_{y}(亿)", f"inv_{y}": f"存货_{y}(亿)",
        f"ar_inv_{y}": f"应收+存货_{y}(亿)", f"ap_{y}": f"应付_{y}(亿)",
        f"advance_{y}": f"预付_{y}(亿)",
        f"ar_inv_prep_{y}": f"应收+存货+预付_{y}(亿)",
    })
for y in _yrs[1:]:
    for pfx, cn in [("rev", "营收"), ("np", "净利"), ("ocf", "现金流"),
                     ("ar", "应收"), ("inv", "存货"), ("ar_inv", "应收存货"),
                     ("ap", "应付"), ("advance", "预付"),
                     ("ar_inv_prep", "应收存货预付")]:
        COL_CN[f"{pfx}_gr_{y}"] = f"{cn}增速_{y}%"
    COL_CN[f"om_chg_{y}"] = f"利润率变化_{y}"

COL_CN.update({
    "q_rev": "最新季营收(亿)", "q_rev_yoy": "最新季营收同比%",
    "q_np": "最新季净利(亿)", "q_np_yoy": "最新季净利同比%",
    "q_ar": "最新季应收(亿)", "q_ar_yoy": "应收同比%",
    "q_inv": "最新季存货(亿)", "q_inv_yoy": "存货同比%",
    "q_ap": "最新季应付(亿)", "q_ap_yoy": "应付同比%",
    "q_advance": "最新季预付(亿)", "q_advance_yoy": "预付同比%",
    "debt_ratio": "资产负债率%", "int_cvg": "利息覆盖",
    "ar_inv_prep_to_rev": "应收存货预付/营收%", "gw_ratio": "商誉/净资产%",
    "cf_to_np": "经营现金流/净利",
})

for p, c in [("1w","1周"),("1m","1月"),("3m","3月"),("6m","6月"),
             ("1y","1年"),("2y","2年"),("3y","3年"),("5y","5年")]:
    COL_CN[f"ret_{p}"] = f"近{c}涨幅%"


# ── 工具 ────────────────────────────────────────────

def _v(val, fmt=".1f"):
    if val is None:
        return "N/A"
    if isinstance(val, float) and np.isnan(val):
        return "N/A"
    try:
        return f"{val:{fmt}}"
    except (ValueError, TypeError):
        return str(val)


PCT_COLS = set()  # columns where value is a percentage
_pct_prefixes = ["rev_gr_", "np_gr_", "ocf_gr_", "ar_gr_", "inv_gr_",
                 "ar_inv_gr_", "ap_gr_", "advance_gr_", "ar_inv_prep_gr_",
                 "om_", "roe_", "debt_ratio",
                 "ar_inv_prep_to_rev", "gw_ratio", "q_rev_yoy", "q_np_yoy",
                 "q_ar_yoy", "q_inv_yoy", "q_ap_yoy", "q_advance_yoy"]
for c in COL_CN:
    for pfx in _pct_prefixes:
        if c == pfx or c.startswith(pfx):
            PCT_COLS.add(c)
            break
for p in ["ret_1w","ret_1m","ret_3m","ret_6m","ret_1y","ret_2y","ret_3y","ret_5y"]:
    PCT_COLS.add(p)


def _vp(val, fmt="+.1f"):
    """Format percentage with % sign."""
    s = _v(val, fmt)
    return s + "%" if s != "N/A" else s


# ── 数据 ────────────────────────────────────────────

@st.cache_data
def load_data():
    df = pd.read_parquet(CACHE_PATH)
    df["concepts"] = df["concepts"].fillna("")
    return df


@st.cache_data
def get_concept_list(df):
    concepts = set()
    for c in df["concepts"]:
        for cname in c.split(","):
            cname = cname.strip()
            if cname:
                concepts.add(cname)
    return sorted(concepts)


@st.cache_data
def get_sw2_list(df, sw1=None):
    if sw1 and sw1 != "全部":
        return sorted(df[df["SW1"] == sw1]["SW2"].dropna().unique())
    return sorted(df["SW2"].dropna().unique())


def filter_dataframe(df, filters):
    mask = pd.Series(True, index=df.index)
    if filters["sw1"] != "全部":
        mask &= df["SW1"] == filters["sw1"]
    if filters["sw2"] != "全部":
        mask &= df["SW2"] == filters["sw2"]
    if filters["concept_keyword"]:
        keywords = [k.strip() for k in filters["concept_keyword"].split(",")]
        for kw in keywords:
            if kw:
                mask &= df["concepts"].str.contains(kw, na=False, regex=False)
    for col, (lo, hi) in filters["ranges"].items():
        if col in df.columns and lo is not None and hi is not None:
            mask &= df[col].between(lo, hi, inclusive="both")
    if filters["status"]:
        mask &= df["status"].isin(filters["status"])
    return df[mask].copy()


# ── 页面 ────────────────────────────────────────────

st.set_page_config(page_title="A 股浏览器", layout="wide")

# ── 模式切换 ──────────────────────────────────────

mode = st.sidebar.radio("模式", ["📋 选股", "🔄 回测"], horizontal=True, label_visibility="collapsed")

if mode == "🔄 回测":
    render_backtest_page()
    st.stop()

st.markdown(
    "<h1 style='font-size:1.6rem;margin-bottom:0'>A 股浏览器</h1>"
    "<p style='color:#888;font-size:0.85rem;margin-top:-0.3rem'>"
    "5207 只 A 股 · 5 年财务+K线 · 同花顺概念 · 申万行业</p>",
    unsafe_allow_html=True,
)

df = load_data()

# ── 侧边栏过滤 ─────────────────────────────────────

st.sidebar.markdown("### 行业")

sw1_list = ["全部"] + sorted(df["SW1"].dropna().unique())
sw1 = st.sidebar.selectbox("SW1 行业", sw1_list, key="sw1")

sw2_list = ["全部"] + get_sw2_list(df, sw1 if sw1 != "全部" else None)
sw2 = st.sidebar.selectbox("SW2 子行业", sw2_list, key="sw2")

st.sidebar.markdown("### 概念")

concept_keyword = st.sidebar.text_input(
    "搜索概念（逗号分隔 = AND）",
    placeholder="算力,低空经济",
    key="concept_kw",
)

st.sidebar.markdown("### 指标范围")

range_cols = {
    "rev_2025": ("营收(亿)", 0, 2000.0),
    "rev_gr_2025": ("营收增速%", -50.0, 200.0),
    "q_rev_yoy": ("最新季营收同比%", -50.0, 200.0),
    "np_2025": ("净利(亿)", -10.0, 100.0),
    "om_2025": ("营业利润率%", -20.0, 50.0),
    "roe_2025": ("ROE%", -20.0, 40.0),
    "debt_ratio": ("负债率%", 0, 100.0),
    "ret_1y": ("近1年涨幅%", -50.0, 500.0),
    "score": ("评分", 9.5, 10.0),
}

ranges = {}
for col, (label, min_v, max_v) in range_cols.items():
    data_min = float(df[col].min()) if df[col].notna().any() else float(min_v)
    data_max = float(df[col].max()) if df[col].notna().any() else float(max_v)
    default_hi = data_max if col not in ("debt_ratio", "score") else float(max_v)
    lo, hi = st.sidebar.slider(
        label,
        min_value=min(data_min, float(min_v)),
        max_value=max(data_max, float(max_v)),
        value=(float(min_v), default_hi),
        step=0.5 if "评分" in label else 1.0,
        key=f"r_{col}",
    )
    ranges[col] = (lo, hi)

st.sidebar.markdown("### 状态")

status_opts = st.sidebar.multiselect(
    "状态",
    ["绿灯", "黄灯", "红灯"],
    default=["绿灯", "黄灯", "红灯"],
    key="status",
)

# ── 候选池 ─────────────────────────────────────────

st.sidebar.markdown("### 候选池")

_pool_file = st.sidebar.file_uploader(
    "上传股票池 CSV",
    type="csv",
    help="文件可含标题行（stock_code）或直接每行一个代码",
)

_pool_codes = None
if _pool_file is not None:
    _raw = _pool_file.getvalue().decode("utf-8").strip().splitlines()
    _first = _raw[0].strip().lower().strip('"')
    if _first in ("stock_code", "code", "代码", "股票代码"):
        _raw = _raw[1:]
    _pool_codes = set()
    for _line in _raw:
        _code = _line.strip().strip('"').strip("'").strip(",")
        if _code:
            _pool_codes.add(_code)
    st.sidebar.caption(f"已加载 {len(_pool_codes)} 只股票")

# ── 刷新缓存 ───────────────────────────────────────

st.sidebar.markdown("---")
if st.sidebar.button("🔄 刷新数据缓存", type="secondary"):
    with st.spinner("正在重建数据缓存（约 6 秒）..."):
        from core.code.profile import build_profile
        from core.code.scoring.scorer import Scorer
        _tmp = build_profile(refresh=True)
        _tmp = Scorer().apply(_tmp)
        _tmp.to_parquet(CACHE_PATH, index=False)
        st.cache_data.clear()
    st.rerun()

# ── 过滤 ───────────────────────────────────────────

filters = {
    "sw1": sw1, "sw2": sw2, "concept_keyword": concept_keyword,
    "ranges": ranges, "status": status_opts,
}

filtered = filter_dataframe(df, filters)

# 候选池过滤
if _pool_codes:
    _pool_matched = filtered["stock_code"].isin(_pool_codes)
    _pool_miss = len(_pool_codes) - _pool_matched.sum()
    filtered = filtered[_pool_matched]
    _pool_label = f" · 池内 {_pool_matched.sum()} 只"
    if _pool_miss:
        _pool_label += f"（{_pool_miss} 只不在过滤结果中）"
else:
    _pool_label = ""

st.markdown(
    f"<span style='color:#888;font-size:0.85rem'>"
    f"共 {len(df):,} 条 · 过滤后 {len(filtered):,} 条{_pool_label}</span>",
    unsafe_allow_html=True,
)

# 显示列
show_cols = [
    "stock_code", "name", "SW2", "concepts",
    "rev_2025", "rev_gr_2025",
    "np_2025", "np_gr_2025",
    "q_rev_yoy", "q_np_yoy",
    "om_2025", "roe_2025", "debt_ratio",
    "ret_1w", "ret_1m", "ret_3m", "ret_1y", "score", "status",
]
available = [c for c in show_cols if c in filtered.columns]

# ── 选中状态 ──────────────────────────────────────

if "selected_code" not in st.session_state:
    st.session_state.selected_code = None

# ── Tabs ───────────────────────────────────────────

_tabs = st.tabs(["⭐ 自选股", "🔮 预判复盘", "📊 概念板块", "📋 选股列表", "📊 详情", "📈 走势", "📡 跟踪雷达", "📊 投资组合"])

def render_concept_page(df):
    """概念板块排行页面"""
    from core.code.concept_analysis import concept_ranking, WIN_LABELS

    has_1d = "ret_1d" in df.columns

    with st.spinner("计算概念排行..."):
        rdf = concept_ranking(min_stocks=3)

    if rdf.empty:
        st.warning("暂无概念板块数据（缓存可能未就绪）")
        return

    # ── 显示方式 ──
    col1, col2, _ = st.columns([1.5, 1.5, 3])
    with col1:
        mode = st.radio("", ["涨幅均值", "排名分位"], horizontal=True, label_visibility="collapsed")
    with col2:
        sort_by = st.selectbox("", ["异动分", "1日", "1周", "1月", "3月", "1年", "3年"],
                               label_visibility="collapsed")

    if not has_1d:
        st.caption("⚠️ 缺少 1 日涨幅数据，点击左侧「刷新数据缓存」后生效")

    show_rank = (mode == "排名分位")

    # ── 排序 ──
    sort_map = {
        "异动分": "divergence",
        "1日": "ret_1d_mean", "1周": "ret_1w_mean", "1月": "ret_1m_mean",
        "3月": "ret_3m_mean", "1年": "ret_1y_mean", "3年": "ret_3y_mean",
    }
    sc = sort_map.get(sort_by, "divergence")
    if sc in rdf.columns:
        rdf = rdf.sort_values(sc, ascending=False).reset_index(drop=True)

    # ── 构建显示表 ──
    all_windows = ["ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_1y", "ret_3y"]
    if not has_1d:
        all_windows = all_windows[1:]

    display = {"概念": rdf["concept"], "N": rdf["N"].astype(int)}
    cfg = {
        "概念": st.column_config.TextColumn("概念"),
        "N": st.column_config.NumberColumn("N", format="%d"),
    }

    for c in all_windows:
        lbl = WIN_LABELS.get(c, c)
        if show_rank:
            display[lbl] = rdf[f"{c}_rank"].round(1)
            cfg[lbl] = st.column_config.NumberColumn(lbl, format="%.1f")
        else:
            display[lbl] = rdf[f"{c}_mean"].round(2)
            cfg[lbl] = st.column_config.NumberColumn(lbl, format="%+.2f%%")

    display["🚀异动"] = rdf["divergence"]
    cfg["🚀异动"] = st.column_config.NumberColumn(
        "🚀异动",
        format="%+.1f",
        help="短期动量(=0.5×1d分位+0.3×1w分位+0.2×1m分位) − 3月排名分位",
    )

    display_df = pd.DataFrame(display)

    st.markdown(f"共 {len(display_df)} 个概念板块 ≥ 3 只成分股")

    # ── 排行表 ──
    st.dataframe(
        display_df,
        column_config=cfg,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=600,
        key="concept_grid",
    )

    # ── 选中概念 → 展开成分股 ──
    sel_state = st.session_state.get("concept_grid")
    selected_concept = None
    if sel_state and sel_state.selection.rows:
        idx = sel_state.selection.rows[0]
        selected_concept = display_df.iloc[idx]["概念"]

    search_c = st.text_input("或搜索概念查看成分股", placeholder="输入概念名称...", key="concept_search")
    if search_c:
        matches = [c for c in rdf["concept"] if search_c.strip().lower() in c.lower()]
        if len(matches) == 1:
            selected_concept = matches[0]
        elif len(matches) > 1:
            st.caption(f"找到 {len(matches)} 个，继续输入")
        elif search_c.strip():
            st.caption("未找到")

    if selected_concept and selected_concept in rdf["concept"].values:
        # 同步到 session_state，供选股列表 tab 使用
        if st.session_state.get("concept_filter") != selected_concept:
            st.session_state["concept_filter"] = selected_concept
        st.markdown(f"**▸ {selected_concept}** — 成分股明细")

        mask = df["concepts"].str.contains(selected_concept, na=False, regex=False)
        stocks = df[mask][["stock_code", "name", "SW2"] + all_windows].copy()
        stocks = stocks.sort_values(all_windows[0], ascending=False, na_position="last")

        stock_cfg = {
            "stock_code": st.column_config.TextColumn("代码", width="small"),
            "name": st.column_config.TextColumn("名称", width="small"),
            "SW2": st.column_config.TextColumn("行业"),
        }
        for c in all_windows:
            lbl = WIN_LABELS.get(c, c)
            stock_cfg[c] = st.column_config.NumberColumn(lbl, format="%+.2f%%")

        st.dataframe(
            stocks,
            column_config=stock_cfg,
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        st.download_button(
            "📥 导出成分股 CSV",
            stocks.to_csv(index=False).encode("utf-8"),
            f"{selected_concept}.csv",
            "text/csv",
        )

        # ── 添加到自选股 ──
        with st.expander("⭐ 添加到自选股", expanded=False):
            _all_tags = {t["_id"]: t["name"] for t in list_tags()}
            _add_code = st.selectbox(
                "选择股票",
                options=range(len(stocks)),
                format_func=lambda i: f"{stocks.iloc[i]['stock_code']} {stocks.iloc[i]['name']}",
                placeholder="选择要添加到自选股的股票...",
                key=f"concept_add_{selected_concept}",
            )
            if _add_code is not None:
                _s = stocks.iloc[_add_code]
                existing = get_candidate_by_code(_s["stock_code"])
                if existing:
                    st.info(f"已在自选股中")
                else:
                    c1, c2 = st.columns([1, 1])
                    with c1:
                        _add_score = st.number_input("推荐分 (0-255)", value=160, min_value=0, max_value=255, key="add_score")
                    with c2:
                        _add_name = _s["name"]
                        _add_price = st.number_input("参考价（可选）", value=0.0, step=0.01, key="add_price")
                    _add_note = st.text_area("备注", placeholder="选股理由...", key="add_note")
                    _add_tag = st.selectbox(
                        "标签",
                        options=list(_all_tags.keys()),
                        format_func=lambda x: _all_tags[x],
                        index=None,
                        placeholder="选择标签...",
                        key="add_tag",
                    )
                    if st.button("✅ 确认添加", type="primary", use_container_width=True, key="concept_add_confirm"):
                        try:
                            _pid = create_candidate(
                                stock_code=_s["stock_code"],
                                name=_add_name,
                                note=_add_note,
                                score=_add_score,
                                tags=[_add_tag] if _add_tag else [],
                                price_when_added=_add_price if _add_price > 0 else None,
                                concept=selected_concept,
                            )
                            st.success(f"已添加到自选股 (id={_pid})")
                            st.rerun()
                        except Exception as _e:
                            st.error(f"添加失败: {_e}")


with _tabs[2]:
    render_concept_page(df)
with _tabs[3]:
    # 概念板块过滤（从板块tab同步过来）
    _cf = st.session_state.get("concept_filter")
    _show_clear = False
    if _cf:
        _cf_mask = filtered["concepts"].str.contains(_cf, na=False, regex=False)
        _cf_count = _cf_mask.sum()
        filtered = filtered[_cf_mask]
        _show_clear = True

    if _show_clear:
        _c1, _c2, _c3 = st.columns([1.5, 2, 6])
        with _c1:
            if st.button("✕ 清除", type="secondary"):
                st.session_state["concept_filter"] = None
                st.rerun()
        with _c2:
            st.caption(f"📊 {_cf}")
        with _c3:
            st.caption(f"筛选后 {len(filtered)} 只")

    # ── 只看自选股 & 搜索（一行） ──
    _col_check, _col_search = st.columns([1, 5])
    with _col_check:
        _cand_only = st.checkbox("⭐ 只看自选股", key="cand_only_filter")
    with _col_search:
        _search_text = st.text_input("", placeholder="🔍 搜索股票（代码/名称，模糊搜索）",
                                     key="stocklist_search", label_visibility="collapsed")
    if _cand_only:
        _cand_codes = [c["stock_code"] for c in list_candidates(limit=500)]
        filtered = filtered[filtered["stock_code"].isin(_cand_codes)]
        st.caption(f"⭐ 只看自选股 · {len(filtered)} 只匹配")
    if _search_text:
        _digits = "".join(filter(str.isdigit, _search_text))
        if _digits:
            _code_mask = filtered["stock_code"].str.replace(r"\D", "", regex=True).str.contains(_digits, na=False)
        else:
            _code_mask = pd.Series(False, index=filtered.index)
        _name_mask = filtered["name"].str.contains(_search_text, na=False)
        filtered = filtered[_code_mask | _name_mask]
        st.caption(f"搜索匹配 {len(filtered)} 只")

    # ── 表格（带单选行选） ──
    _display = filtered[available].copy()
    st.dataframe(
        _display,
        column_config={
            "stock_code": st.column_config.TextColumn("代码", width="small"),
            "name": st.column_config.TextColumn("名称", width="small"),
            "SW2": st.column_config.TextColumn("子行业"),
            "concepts": st.column_config.TextColumn("概念", width="medium"),
            "rev_2025": st.column_config.NumberColumn("营收(亿)", format="%.1f"),
            "rev_gr_2025": st.column_config.NumberColumn("营收增速%", format="%+.1f%%"),
            "np_2025": st.column_config.NumberColumn("净利(亿)", format="%.1f"),
            "np_gr_2025": st.column_config.NumberColumn("净利增速%", format="%+.1f%%"),
            "q_rev_yoy": st.column_config.NumberColumn("q营收%", format="%+.1f%%"),
            "q_np_yoy": st.column_config.NumberColumn("q净利%", format="%+.1f%%"),
            "om_2025": st.column_config.NumberColumn("营业利润率%", format="%.1f%%"),
            "roe_2025": st.column_config.NumberColumn("ROE%", format="%.1f%%"),
            "debt_ratio": st.column_config.NumberColumn("负债率%", format="%.1f%%"),
            "ret_1w": st.column_config.NumberColumn("涨幅1W%", format="%+.1f%%"),
            "ret_1m": st.column_config.NumberColumn("涨幅1M%", format="%+.1f%%"),
            "ret_3m": st.column_config.NumberColumn("涨幅3M%", format="%+.1f%%"),
            "ret_1y": st.column_config.NumberColumn("涨幅1Y%", format="%+.1f%%"),
            "score": st.column_config.NumberColumn("评分", format="%.1f"),
            "status": st.column_config.TextColumn("状态", width="small"),
        },
        width="stretch",
        height=600,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="stock_grid",
    )

    # 处理行选
    _sel = st.session_state.get("stock_grid")
    if _sel and _sel.selection.rows:
        st.session_state.selected_code = filtered.iloc[_sel.selection.rows[0]]["stock_code"]

    # 兜底下拉选股
    _picker = st.selectbox(
        "或在下方选择",
        options=range(len(filtered)),
        format_func=lambda i: f"{filtered.iloc[i]['stock_code']} {filtered.iloc[i]['name']}",
        index=None,
        placeholder="从过滤结果中选择一支股票...",
    )
    if _picker is not None:
        st.session_state.selected_code = filtered.iloc[_picker]["stock_code"]

    st.download_button(
        "📥 导出过滤结果为 CSV",
        filtered[available].to_csv(index=False).encode("utf-8"),
        "filtered_stocks.csv",
        "text/csv",
    )

    # ── 从选股列表添加到自选股 ──
    with st.expander("⭐ 添加到自选股", expanded=False):
        _all_tags = {t["_id"]: t["name"] for t in list_tags()}
        _sel_idx = st.selectbox(
            "选择股票",
            options=range(len(filtered)),
            format_func=lambda i: f"{filtered.iloc[i]['stock_code']} {filtered.iloc[i]['name']}",
            index=None,
            placeholder="从过滤结果中选择...",
            key="stocklist_add_sel",
        )
        if _sel_idx is not None:
            _s = filtered.iloc[_sel_idx]
            _s_concept = (_s.get("concepts") or "")[:60]
            _cf_for_add = st.session_state.get("concept_filter", "") or _s_concept
            if get_candidate_by_code(_s["stock_code"]):
                st.info("已在自选股中")
            else:
                c1, c2 = st.columns([1, 1])
                with c1:
                    _add_score = st.number_input("推荐分 (0-255)", value=160, min_value=0,
                                                  max_value=255, key="sl_add_score")
                with c2:
                    _add_price = st.number_input("参考价", value=0.0, step=0.01, key="sl_add_price")
                _add_note = st.text_area("备注", placeholder="选股理由...", key="sl_add_note")
                _add_tag = st.selectbox(
                    "标签", options=list(_all_tags.keys()),
                    format_func=lambda x: _all_tags[x], index=None,
                    placeholder="选择标签...", key="sl_add_tag",
                )
                if st.button("✅ 确认添加", type="primary", use_container_width=True, key="stocklist_add_confirm"):
                    try:
                        _pid = create_candidate(
                            stock_code=_s["stock_code"], name=_s["name"],
                            note=_add_note, score=_add_score, tags=[_add_tag] if _add_tag else [],
                            price_when_added=_add_price if _add_price > 0 else None,
                            concept=_cf_for_add or "",
                        )
                        st.success(f"已添加到自选股 (id={_pid})")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"添加失败: {_e}")

with _tabs[4]:
    _search = st.text_input(
        "搜索股票（代码或名称）",
        placeholder="输入股票代码或名称，如 300395 或 菲利华",
    )
    if _search:
        _digits = "".join(filter(str.isdigit, _search))
        _match = df[
            df["stock_code"].str.replace(r"\D", "", regex=True).str.contains(_digits, na=False)
            | df["name"].str.contains(_search, na=False)
        ]
        if len(_match) == 1:
            st.session_state.selected_code = _match.iloc[0]["stock_code"]
        elif len(_match) > 1:
            st.info(f"找到 {len(_match)} 支匹配股票，可在列表中点选或继续输入")
        elif _search:
            st.warning("未找到匹配股票")

    # ── 详情展示 ──
    _sc = st.session_state.selected_code
    if _sc and (_sc in df["stock_code"].values):
        _s = df[df["stock_code"] == _sc].iloc[0]

        st.markdown(
            f"<h3 style='margin-bottom:2px'>{_s['name']} ({_s['stock_code']})  "
            f"<span style='font-size:0.8rem;color:#888'>"
            f"SW2: {_s.get('SW2', '')}　"
            f"评分: {_v(_s.get('score'), '.1f')}　"
            f"CF/NP: {_v(_s.get('cf_to_np'), '.2f')}　"
            f"状态: {_s.get('status', '')}</span></h3>",
            unsafe_allow_html=True,
        )
        if pd.notna(_s.get("concepts")):
            st.markdown(
                f"<span style='font-size:0.78rem;color:#666'>"
                f"概念: {_s['concepts']}</span>",
                unsafe_allow_html=True,
            )

        # ── 5年财务趋势（含柱状图） ──
        st.markdown("**5年财务趋势（点击指标行查看柱状图）**")
        _yrs = [2021, 2022, 2023, 2024, 2025]
        _trend_metrics = [
            ("营收(亿)",      "rev_{}",      False),
            ("营收增速%",    "rev_gr_{}",   True),
            ("净利(亿)",     "np_{}",       False),
            ("净利增速%",   "np_gr_{}",    True),
            ("营业利润率%",  "om_{}",       True),
            ("ROE%",         "roe_{}",      True),
            ("经营现金流(亿)", "ocf_{}",    False),
            ("应收(亿)",     "ar_{}",       False),
            ("应收增速%",   "ar_gr_{}",    True),
            ("存货(亿)",     "inv_{}",      False),
            ("存货增速%",   "inv_gr_{}",   True),
            ("预付(亿)",     "advance_{}",  False),
            ("预付增速%",   "advance_gr_{}", True),
            ("应付(亿)",     "ap_{}",       False),
            ("应付增速%",   "ap_gr_{}",    True),
        ]
        _tdf_data = {}
        for _label, _tmpl, _ in _trend_metrics:
            _tdf_data[_label] = {_y: _s.get(_tmpl.format(_y), np.nan) for _y in _yrs}
        _tdf = pd.DataFrame(_tdf_data).T.reset_index()
        _tdf.columns = ["指标"] + [str(y) for y in _yrs]
        for _y in _yrs:
            _tdf[str(_y)] = _tdf[str(_y)].astype(object)
        for _i, _r in _tdf.iterrows():
            _is_pct = _r["指标"].endswith("%")
            for _y in _yrs:
                _rv = _r[str(_y)]
                if pd.isna(_rv):
                    _tdf.at[_i, str(_y)] = "N/A"
                elif _is_pct:
                    _tdf.at[_i, str(_y)] = f"{_rv:+.1f}%"
                else:
                    _tdf.at[_i, str(_y)] = f"{_rv:.1f}"
        _trend_key = f"_trend_{_sc}"
        _tl, _tr = st.columns([1, 1])
        with _tl:
            st.dataframe(
                _tdf, hide_index=True, width="stretch", height=640,
                on_select="rerun", selection_mode="single-row",
                key=_trend_key,
            )
        _t_sel = st.session_state.get(_trend_key)
        with _tr:
            if _t_sel and _t_sel.selection.rows:
                _t_idx = _t_sel.selection.rows[0]
                _t_name = _tdf.iloc[_t_idx]["指标"]
                _t_vals = {str(y): _tdf_data[_t_name][y] for y in _yrs
                           if not pd.isna(_tdf_data[_t_name][y])}
                if len(_t_vals) > 1:
                    _t_chart = pd.DataFrame(
                        {_t_name: list(_t_vals.values())},
                        index=list(_t_vals.keys()),
                    )
                    st.bar_chart(_t_chart, height=640)

        st.divider()

        # ── 最新季度（含柱状图） ──
        st.markdown("**最新季度（点击指标行查看两年对比柱状图）**")

        def _prev_q(_cv, _yv):
            if pd.isna(_cv) or pd.isna(_yv):
                return np.nan
            return _cv / (1 + _yv / 100)

        _q_metrics = [
            ("最新季营收(亿)",  _v(_s.get("q_rev"), ".1f"),       _s.get("q_rev"),    _s.get("q_rev_yoy")),
            ("营收同比",        _vp(_s.get("q_rev_yoy")),          None,               None),
            ("最新季净利(亿)", _v(_s.get("q_np"), ".1f"),        _s.get("q_np"),     _s.get("q_np_yoy")),
            ("净利同比",        _vp(_s.get("q_np_yoy")),           None,               None),
            ("最新季应收(亿)", _v(_s.get("q_ar"), ".1f"),        _s.get("q_ar"),     _s.get("q_ar_yoy")),
            ("应收同比",        _vp(_s.get("q_ar_yoy")),           None,               None),
            ("最新季存货(亿)", _v(_s.get("q_inv"), ".1f"),       _s.get("q_inv"),    _s.get("q_inv_yoy")),
            ("存货同比",        _vp(_s.get("q_inv_yoy")),          None,               None),
            ("最新季预付(亿)", _v(_s.get("q_advance"), ".1f"),   _s.get("q_advance"),_s.get("q_advance_yoy")),
            ("预付同比",        _vp(_s.get("q_advance_yoy")),      None,               None),
            ("最新季应付(亿)", _v(_s.get("q_ap"), ".1f"),        _s.get("q_ap"),     _s.get("q_ap_yoy")),
            ("应付同比",        _vp(_s.get("q_ap_yoy")),           None,               None),
        ]
        _q_df = pd.DataFrame([{"指标": m[0], "值": m[1]} for m in _q_metrics])
        _q_key = f"_q_{_sc}"
        _ql, _qm, _qr = st.columns([2, 1, 1])
        with _ql:
            st.dataframe(
                _q_df, hide_index=True, width="stretch", height=500,
                on_select="rerun", selection_mode="single-row",
                key=_q_key,
            )
        _q_sel = st.session_state.get(_q_key)
        with _qm:
            if _q_sel and _q_sel.selection.rows:
                _q_idx = _q_sel.selection.rows[0]
                _q_name = _q_df.iloc[_q_idx]["指标"]
                _cur_v = _q_metrics[_q_idx][2]
                _yoy_v = _q_metrics[_q_idx][3]
                _prev_v = _prev_q(_cur_v, _yoy_v)
                if not pd.isna(_prev_v):
                    _q_chart = pd.DataFrame(
                        {_q_name: [_prev_v, _cur_v]},
                        index=["去年同期", "本期"],
                    )
                    st.bar_chart(_q_chart, height=500)

        # ── 安全指标 ──
        st.markdown("**安全指标**")
        _sdata = {
            "资产负债率%": _vp(_s.get("debt_ratio")),
            "利息覆盖": _v(_s.get("int_cvg"), ".1f"),
            "应收存货预付/营收%": _vp(_s.get("ar_inv_prep_to_rev")),
            "商誉/净资产%": _vp(_s.get("gw_ratio")),
            "经营CF/净利": _v(_s.get("cf_to_np"), ".2f"),
        }
        st.dataframe(
            pd.DataFrame([_sdata]),
            column_config={c: st.column_config.TextColumn(c) for c in _sdata},
            hide_index=True, width="stretch",
        )

        # ── 收益率 & 评分 ──
        st.markdown("**收益率 & 评分**")
        _rdata = {}
        for _p, _c in [("1w","1周"),("1m","1月"),("3m","3月"),
                        ("6m","6月"),("1y","1年"),("2y","2年"),
                        ("3y","3年"),("5y","5年")]:
            _rdata[f"{_c}涨幅"] = _vp(_s.get(f"ret_{_p}"))
        _rdata["总分"] = _v(_s.get("score"), ".1f")
        _rdata["A盈利质量"] = _v(_s.get("score_A"), ".1f")
        _rdata["B现金流安全"] = _v(_s.get("score_B"), ".1f")
        _rdata["C资产质量"] = _v(_s.get("score_C"), ".1f")
        _rdata["D破绽"] = _v(_s.get("score_D"), ".1f")
        st.dataframe(
            pd.DataFrame([_rdata]),
            column_config={c: st.column_config.TextColumn(c) for c in _rdata},
            hide_index=True, width="stretch",
        )

        # ── 全部原始数据 ──
        st.markdown("**全部原始数据**")
        _detail = pd.DataFrame({
            "列名": [COL_CN.get(c, c) for c in _s.index],
            "值": [
                _vp(_s[c]) if c in PCT_COLS
                else (_v(_s[c], ".2f") if isinstance(_s[c], (int, float))
                      else str(_s[c]))
                for c in _s.index
            ],
        })
        st.dataframe(_detail, hide_index=True, width="stretch", height=4000)

# ── K 线数据缓存 ──────────────────────────────────

@st.cache_data
def load_kline(code):
    fp = BASE / "export" / "data" / "kline" / f"{code}.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp)
        df["date"] = pd.to_datetime(df["time"], unit="ms")
        df = df[df["close"].notna() & (df["close"] > 0)].copy()
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


# ── 跟踪雷达 Tab ──────────────────────────────────

def render_tracking_radar(df):
    """📡 跟踪雷达 — 配置组合管理"""
    try:
        from core.code.tracking_radar import (
            list_sets, load_set, save_set, delete_set,
            copy_set, rename_set,
        )
    except Exception as e:
        import traceback
        st.error(f"跟踪雷达模块导入失败: {e}")
        with st.expander("错误详情"):
            st.code(traceback.format_exc())
        return

    # ── State init ──
    if "tr_current" not in st.session_state:
        st.session_state.tr_current = None  # (name, kind)
    if "tr_configs" not in st.session_state:
        st.session_state.tr_configs = None
    if "tr_show_path" not in st.session_state:
        st.session_state.tr_show_path = False
    if "tr_show_new_dialog" not in st.session_state:
        st.session_state.tr_show_new_dialog = False
    if "tr_show_rename_dialog" not in st.session_state:
        st.session_state.tr_show_rename_dialog = False
    if "tr_show_delete_confirm" not in st.session_state:
        st.session_state.tr_show_delete_confirm = False

    # ── 当前配置（在列布局前读取）──
    configs = st.session_state.tr_configs
    current = st.session_state.tr_current

    # ── Left: 组合列表（紧凑版）──
    left, right = st.columns([0.19, 0.81])

    with left:
        # 按钮不换行
        st.markdown("""
        <style>
        div[data-testid="column"] button,
        div[data-testid="column"] button p {
            white-space: nowrap !important;
            overflow: visible !important;
        }
        </style>
        """, unsafe_allow_html=True)

        st.markdown("**跟踪组合**")
        all_sets = list_sets()
        default_sets = [(n, k) for n, k in all_sets if k == "default"]
        custom_sets = [(n, k) for n, k in all_sets if k == "custom"]
        selected = current

        def _load_set(name, kind):
            st.session_state.tr_current = (name, kind)
            st.session_state.tr_configs = load_set(name, kind)
            st.session_state.tr_show_path = False
            st.rerun()

        if default_sets:
            st.markdown("系统模板")
            for name, kind in default_sets:
                active = (selected == (name, kind))
                if st.button(f"{'📄' if active else '  '} {name}", key=f"tr_load_{kind}_{name}",
                             use_container_width=True, type="primary" if active else "secondary"):
                    _load_set(name, kind)

        if custom_sets:
            st.markdown("我的组合")
            for name, kind in custom_sets:
                active = (selected == (name, kind))
                if st.button(f"{'📄' if active else '  '} {name}", key=f"tr_load_{kind}_{name}",
                             use_container_width=True, type="primary" if active else "secondary"):
                    _load_set(name, kind)

        if st.button("➕ 新建组合", use_container_width=True, key="tr_new"):
            st.session_state.tr_show_new_dialog = True
            st.rerun()

        if st.session_state.tr_show_new_dialog:
            with st.container(border=True):
                new_name = st.text_input("组合名称", key="tr_new_name", placeholder="如 持仓跟踪", label_visibility="collapsed")
                all_templates = [(n, k) for n, k in all_sets]
                tmpl_options = [f"{'📄' if k=='default' else '📁'} {n}" for n, k in all_templates]
                tmpl_idx = st.selectbox("从模板", range(len(tmpl_options)), format_func=lambda i: tmpl_options[i],
                                        key="tr_new_tmpl", label_visibility="collapsed")
                tmpl_name, tmpl_kind = all_templates[tmpl_idx]
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("创建", key="tr_new_confirm", use_container_width=True):
                        if new_name.strip():
                            try:
                                copy_set(new_name.strip(), tmpl_name, tmpl_kind)
                                st.session_state.tr_current = (new_name.strip(), "custom")
                                st.session_state.tr_configs = load_set(new_name.strip(), "custom")
                                st.session_state.tr_show_new_dialog = False
                                st.rerun()
                            except FileExistsError: st.error(f"组合 '{new_name}' 已存在")
                        else: st.warning("请输入名称")
                with c2:
                    if st.button("取消", key="tr_new_cancel", use_container_width=True):
                        st.session_state.tr_show_new_dialog = False; st.rerun()

        # ── 操作按钮（紧凑行） ──
        if configs is not None:
            set_name, set_kind = current
            is_readonly = (set_kind == "default")
            edited_val = st.session_state.get(f"tr_ace_{set_name}") or "{}"

            save_path, ops_path = st.columns([1, 1])

            with save_path:
                if not is_readonly:
                    if st.button("💾 保存", use_container_width=True, key="tr_save"):
                        try:
                            parsed = json.loads(edited_val)
                            st.session_state.tr_configs = parsed
                            save_set(set_name, parsed)
                            st.success("已保存"); st.rerun()
                        except json.JSONDecodeError as e: st.error(f"JSON 格式错误: {e}")

            with ops_path:
                if st.button("📋 路径", use_container_width=True, key="tr_show_path_btn"):
                    st.session_state.tr_show_path = not st.session_state.tr_show_path; st.rerun()

            if st.session_state.tr_show_path:
                from core.code.tracking_radar import get_path
                st.code(get_path(set_name, set_kind) + "/tracking.json", language="text")
                st.caption("复制路径，告诉我。我读取配置、搜索线索、生成报告写入 Obsidian。")

            # 自定义组合的管理按钮（一行）
            if selected and selected[1] == "custom" and not st.session_state.tr_show_new_dialog:
                c1, c2 = st.columns([1, 1])
                with c1:
                    if st.button("✏️ 重命名", use_container_width=True, key="tr_rename_btn"):
                        st.session_state.tr_show_rename_dialog = True; st.rerun()
                    if st.session_state.tr_show_rename_dialog:
                        new_name = st.text_input("新名称", value=selected[0], key="tr_rename_input", label_visibility="collapsed")
                        c3, c4 = st.columns(2)
                        with c3:
                            if st.button("确认", key="tr_rename_confirm", use_container_width=True):
                                if new_name.strip() and new_name.strip() != selected[0]:
                                    try:
                                        rename_set(selected[0], new_name.strip())
                                        st.session_state.tr_current = (new_name.strip(), "custom")
                                        st.session_state.tr_show_rename_dialog = False; st.rerun()
                                    except FileExistsError: st.error(f"名称 '{new_name}' 已存在")
                                else: st.session_state.tr_show_rename_dialog = False; st.rerun()
                        with c4:
                            if st.button("取消", key="tr_rename_cancel", use_container_width=True):
                                st.session_state.tr_show_rename_dialog = False; st.rerun()
                with c2:
                    if st.button("🗑️ 删除", use_container_width=True, key="tr_delete_btn"):
                        st.session_state.tr_show_delete_confirm = True; st.rerun()
                    if st.session_state.tr_show_delete_confirm:
                        st.warning(f"删除 '{selected[0]}'？")
                        c5, c6 = st.columns(2)
                        with c5:
                            if st.button("确认", key="tr_delete_confirm", use_container_width=True):
                                delete_set(selected[0])
                                st.session_state.tr_current = None; st.session_state.tr_configs = None
                                st.session_state.tr_show_path = False; st.session_state.tr_show_delete_confirm = False; st.rerun()
                        with c6:
                            if st.button("取消", key="tr_delete_cancel", use_container_width=True):
                                st.session_state.tr_show_delete_confirm = False; st.rerun()

    # ── Right: 编辑器 ──
    with right:
        if configs is None:
            st.info("← 从左侧选择一个跟踪组合")
        else:
            set_name, set_kind = current
            is_readonly = (set_kind == "default")

            # ── JSON 编辑器 (Ace Editor) ──
            try:
                text = json.dumps(configs, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                text = "{}"

            readonly_label = "（只读预览）" if is_readonly else ""
            edited = st_ace(
                value=text,
                language="json",
                theme="chrome",
                height=1000,
                min_lines=30,
                font_size=13,
                tab_size=2,
                wrap=False,
                show_gutter=True,
                readonly=is_readonly,
                auto_update=True,
                key=f"tr_ace_{set_name}",
            )

            # 只读提示
            if is_readonly and edited != text:
                st.caption("⚠️ 系统模板为只读。如需修改请「新建组合」从模板复制。")

# ── 自选股 Tab ─────────────────────────────────

def render_candidates_page(df):
    """⭐ 自选股 — 候选股浏览和管理"""
    cand_list = list_candidates(limit=100)

    if not cand_list:
        st.info("暂无自选股。在「概念板块」中浏览股票时，点击「添加到自选股」按钮添加。")
        return

    # ── 标签名映射 ──
    _tag_map = {t["_id"]: t["name"] for t in list_tags()}

    # ── 展示表 ──
    rows = []
    for c in cand_list:
        tag_names = ", ".join(_tag_map.get(tid, str(tid)[:8]) for tid in (c.get("tags") or []))
        rows.append({
            "代码": c["stock_code"],
            "名称": c["name"],
            "推荐分": c.get("score", "-"),
            "标签": tag_names,
            "概念板块": c.get("concept", ""),
            "备注": c.get("note") or "",
            "添加时间": c.get("created_at").strftime("%m-%d") if c.get("created_at") else "",
        })

    display = pd.DataFrame(rows)

    _sel_state = st.dataframe(
        display,
        column_config={
            "代码": st.column_config.TextColumn("代码", width=20),
            "名称": st.column_config.TextColumn("名称", width=20),
            "推荐分": st.column_config.TextColumn("推荐分", width=1),
            "标签": st.column_config.TextColumn("标签", width=10),
            "概念板块": st.column_config.TextColumn("概念板块", width=100),
            "备注": st.column_config.TextColumn("备注", width=300),
            "添加时间": st.column_config.TextColumn("添加", width=20),
        },
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=400,
        key="candidates_grid",
    )

    # ── 选中 → 联动详情/走势 ──
    if _sel_state and _sel_state.selection.rows:
        idx = _sel_state.selection.rows[0]
        if idx < len(cand_list):
            st.session_state.selected_code = cand_list[idx]["stock_code"]

    # ── 操作区 ──
    with st.expander("✏️ 编辑自选股", expanded=False):
        select_opts = {c["_id"]: f"{c['stock_code']} {c['name']} ({c.get('score', '-')}分)"
                       for c in cand_list}
        if select_opts:
            sel_id = st.selectbox(
                "选择要编辑的自选股",
                options=list(select_opts.keys()),
                format_func=lambda x: select_opts[x],
                key="cand_edit_select",
            )
            cand = next(c for c in cand_list if c["_id"] == sel_id)

            new_note = st.text_area("备注", value=cand.get("note", ""), key=f"cand_note_{sel_id}")
            new_score = st.number_input("推荐分 (0-255)", value=int(cand.get("score", 128)),
                                        min_value=0, max_value=255, key=f"cand_score_{sel_id}")

            all_tags = {t["_id"]: t["name"] for t in list_tags()}
            current_tag = (cand.get("tags") or [None])[0]
            new_tag = st.selectbox(
                "标签",
                options=list(all_tags.keys()),
                index=list(all_tags.keys()).index(current_tag) if current_tag and current_tag in all_tags else 0,
                format_func=lambda x: all_tags.get(x, x),
                key=f"cand_tag_{sel_id}",
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("💾 保存修改", type="primary", use_container_width=True):
                    update_candidate(sel_id, {"note": new_note, "score": new_score, "tags": [new_tag]})
                    st.success("已更新")
                    st.rerun()
            with col_b:
                if st.button("🗑️ 删除", use_container_width=True):
                    delete_candidate(sel_id)
                    st.session_state.selected_code = None
                    st.success("已删除")
                    st.rerun()


# ── 走势 Tab ───────────────────────────────────────

with _tabs[5]:
    st.markdown("#### 📈 走势 & 形态匹配")

    # 当前选中的股票
    _chart_code = st.session_state.get("selected_code")

    col1, col2 = st.columns([2, 1])
    with col1:
        _search_chart = st.text_input(
            "搜索股票（代码或名称）",
            placeholder="输入代码或名称，如 300395 或 菲利华",
            key="chart_search",
        )
        if _search_chart:
            _digits = "".join(filter(str.isdigit, _search_chart))
            if _digits:
                _match = df[df["stock_code"].str.replace(r"\D", "", regex=True).str.contains(_digits, na=False)]
            else:
                _match = df[df["name"].str.contains(_search_chart, na=False)]
            if len(_match) == 1:
                _chart_code = _match.iloc[0]["stock_code"]
            elif len(_match) > 1:
                st.caption(f"找到 {len(_match)} 支匹配股票，继续输入")
            elif _search_chart:
                st.caption("未找到")

    with col2:
        if _chart_code and _chart_code in df["stock_code"].values:
            _r = df[df["stock_code"] == _chart_code].iloc[0]
            st.markdown(
                f"**{_r['name']}** ({_chart_code})  "
                f"评分 {_v(_r.get('score'),'.1f')} {_r.get('status','')}"
            )

    _can_chart = (_chart_code is not None and _chart_code in df["stock_code"].values)

    if not _can_chart:
        st.info("👆 在「选股列表」中点选一支股票，或在搜索框输入")

    if _can_chart:
        _k = load_kline(_chart_code)
        if _k is None or len(_k) < 60:
            st.warning("K 线数据不足")
            _can_chart = False

    if _can_chart:
        # ── 参数区 ──
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _w = st.number_input("匹配窗口(天)", min_value=10, max_value=60, value=20, key="pm_w")
        with c2:
            _k_top = st.number_input("匹配数", min_value=3, max_value=10, value=5, key="pm_k")
        with c3:
            _la = st.number_input("看后(天)", min_value=5, max_value=30, value=10, key="pm_la")
        with c4:
            _months = st.selectbox("显示范围", ["3月", "6月", "1年", "全部"], index=2, key="pm_range")
        _days_map = {"3月": 63, "6月": 126, "1年": 252, "全部": len(_k)}
        _lookback = _days_map.get(_months, 63)

        _do_predict = st.button("🔍 预测未来走势", type="primary", use_container_width=True)

        # ── 构建主 K 线图（始终显示） ──

        _k_chart = _k.tail(_lookback).copy().reset_index(drop=True)
        _k_chart["date_str"] = _k_chart["date"].dt.strftime("%Y-%m-%d")

        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import numpy as np

        _fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.7, 0.3], vertical_spacing=0.04,
        )

        _fig.add_trace(
            go.Candlestick(
                x=_k_chart["date"], name="",
                open=_k_chart["open"], high=_k_chart["high"],
                low=_k_chart["low"], close=_k_chart["close"],
                increasing_line_color="#ef5350",
                decreasing_line_color="#26a69a",
                showlegend=False,
            ),
            row=1, col=1,
        )

        _colors_vol = np.where(_k_chart["close"] >= _k_chart["open"], "#ef5350", "#26a69a")
        _fig.add_trace(
            go.Bar(x=_k_chart["date"], y=_k_chart["volume"], name="",
                   marker_color=_colors_vol, showlegend=False),
            row=2, col=1,
        )

        _fig.update_layout(
            height=500, margin=dict(l=20, r=20, t=10, b=10),
            xaxis_rangeslider_visible=False,
            hovermode="x unified",
        )
        _fig.update_yaxes(title_text="价格", row=1, col=1)
        _fig.update_yaxes(title_text="成交量", row=2, col=1)

        _MATCH_COLORS_BG = ["rgba(255,99,71,0.15)", "rgba(30,144,255,0.15)",
                            "rgba(50,205,50,0.15)", "rgba(255,165,0,0.15)",
                            "rgba(147,112,219,0.15)"]
        _MATCH_LINE_COLORS = ["#ff6347", "#1e90ff", "#32cd32", "#ffa500", "#9370db"]

        # ── 预测 ──
        if _do_predict:
            with st.spinner("正在进行形态匹配..."):
                from core.code.pattern_matcher import PatternMatcher
                _pm = PatternMatcher()
                _result = _pm.match(
                    _chart_code, window=_w, top_k=_k_top, lookahead=_la,
                )

            if _result is None or not _result.matches:
                st.warning("未能找到足够相似的形态（数据不足或相似度低于门槛）")
            else:
                _chart_start = _k_chart["date"].iloc[0]
                _chart_end = _k_chart["date"].iloc[-1]

                for _i, _m in enumerate(_result.matches):
                    _ms = pd.Timestamp(_m.start_date)
                    _me = pd.Timestamp(_m.end_date)
                    if _chart_start <= _ms <= _chart_end:
                        _fig.add_vrect(
                            x0=_ms, x1=_me,
                            fillcolor=_MATCH_COLORS_BG[_i],
                            layer="below", line_width=0,
                        )

                _s = _result.stats
                if _s:
                    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
                    sc1.metric("胜率", f"{_s['win_rate']}%", f"{_s['positive_count']}/{_s['total_count']}")
                    sc2.metric("中位数收益", f"{_s['median_return']:+.2f}%")
                    sc3.metric("平均收益", f"{_s['mean_return']:+.2f}%")
                    sc4.metric("最高", f"{_s['max_return']:+.2f}%")
                    sc5.metric("最低", f"{_s['min_return']:+.2f}%")

                st.markdown("##### 形态对比 & 后续走势")
                for _i, _m in enumerate(_result.matches):
                    _c = _MATCH_LINE_COLORS[_i]
                    _pred_norm, _pred_x = [], []
                    if _m.after_close and len(_m.after_close) > 0:
                        _after_rets = [(_m.after_close[j] / _m.after_close[0] - 1) * 100 for j in range(len(_m.after_close))]
                        _pred_base = _m.match_norm_close[-1]
                        _pred_norm = [_pred_base * (1 + r / 100) for r in _after_rets]
                        _pred_x = list(range(len(_m.match_norm_close) - 1, len(_m.match_norm_close) - 1 + len(_pred_norm)))

                    _cur_x = list(range(len(_result.current_norm_close)))
                    _match_x = list(range(len(_m.match_norm_close)))

                    _fig2 = make_subplots(rows=1, cols=1)
                    _fig2.add_trace(go.Scatter(x=_cur_x, y=_result.current_norm_close, mode="lines+markers", name="当前走势", line=dict(color="black", width=2), marker=dict(size=3)))
                    _fig2.add_trace(go.Scatter(x=_match_x, y=_m.match_norm_close, mode="lines+markers", name=f"#{_m.rank} 历史相似", line=dict(color=_c, width=2, dash="dash"), marker=dict(size=3)))
                    if _pred_norm:
                        _fig2.add_trace(go.Scatter(x=_pred_x, y=_pred_norm, mode="lines+markers", name=f"#{_m.rank} 后续({_m.after_return:+.1f}%)", line=dict(color=_c, width=2, dash="dot"), marker=dict(size=4, symbol="triangle-up")))

                    _fig2.update_layout(height=220, margin=dict(l=10, r=10, t=25, b=10), legend=dict(orientation="h", y=1.1, font=dict(size=10)), hovermode="x unified", title=dict(text=f"#{_m.rank}  {_m.start_date}~{_m.end_date}  k线相关={_m.corr_close:.3f}  量相关={_m.corr_volume:.3f}  后续{_la}天:{_m.after_return:+.2f}%  (高:{_m.after_high:+.1f}%  低:{_m.after_low:+.1f}%)", font=dict(size=11)))
                    _fig2.update_yaxes(title_text="归一化价格")
                    st.plotly_chart(_fig2, use_container_width=True, key=f"pm_chart_{_i}")

        # ── 显示主图 ──
        st.plotly_chart(_fig, use_container_width=True, key="main_kline")

# ── 跟踪雷达 Tab ──────────────────────────────────

with _tabs[6]:
    try:
        render_tracking_radar(df)
    except Exception as e:
        import traceback
        st.error(f"跟踪雷达错误: {e}")
        with st.expander("错误详情"):
            st.code(traceback.format_exc())

# ── 预判复盘 Tab ──────────────────────────────────

with _tabs[1]:
    render_predictions()

# ── 投资组合 Tab ──────────────────────────────────

with _tabs[7]:
    render_portfolio()

# ── 自选股 Tab ────────────────────────────────────

with _tabs[0]:
    render_candidates_page(df)
