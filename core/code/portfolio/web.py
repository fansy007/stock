"""Streamlit 投资组合页面。

在 app.py 中引用：
    with _tabs[7]:
        from core.code.portfolio.web import render_portfolio
        render_portfolio()
"""

import streamlit as st
import pandas as pd
from datetime import datetime

from core.code.portfolio.db import (
    create_log,
    get_log,
    get_log_by_date,
    list_logs,
    update_log,
    delete_log,
    latest_log,
)


def render_portfolio():
    st.markdown(
        "<h3 style='margin-bottom:0'>📊 投资组合</h3>"
        "<p style='color:#888;font-size:0.85rem;margin-top:-0.2rem'>"
        "每日总资产 · 持仓 · 成交</p>",
        unsafe_allow_html=True,
    )

    tab_labels = ["📊 总览", "📋 持仓", "📝 成交", "➕ 录入"]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_overview()
    with tabs[1]:
        _render_holdings()
    with tabs[2]:
        _render_trades()
    with tabs[3]:
        _render_entry()


# ── 总览 ──


def _render_overview():
    latest = latest_log()
    all_logs = list_logs(limit=365)

    if not latest:
        st.info("暂无记录。去「➕ 录入」页面添加第一条。")
        return

    # 最新快照卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总资产", f"{latest.get('total_assets', '-'):,.2f}" if latest.get('total_assets') else "-")
    with col2:
        st.metric("总市值", f"{latest.get('market_value', '-'):,.2f}" if latest.get('market_value') else "-")
    with col3:
        dp = latest.get("daily_pnl")
        st.metric("当日盈亏", f"{dp:+,.2f}" if dp else "-")
    with col4:
        tp = latest.get("total_pnl")
        st.metric("总盈亏", f"{tp:+,.2f}" if tp else "-")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"资金余额: {latest.get('cash_balance', '-'):,.2f}" if latest.get('cash_balance') is not None else "")
    with col2:
        st.caption(f"可取: {latest.get('withdrawable', '-'):,.2f}" if latest.get('withdrawable') is not None else "")
    with col3:
        st.caption(f"可用: {latest.get('available', '-'):,.2f}" if latest.get('available') is not None else "")

    st.caption(f"📅 最近更新: {latest['date']}")

    st.divider()

    # 总资产趋势图
    if all_logs:
        rows = []
        for log in all_logs:
            ta = log.get("total_assets")
            if ta is not None:
                rows.append({"date": log["date"], "总资产": ta})
        if len(rows) >= 2:
            df = pd.DataFrame(rows).sort_values("date")
            st.line_chart(df.set_index("date"), use_container_width=True)
        elif len(rows) == 1:
            st.info("只有一条记录，积累更多数据后显示趋势图。")
        else:
            st.info("暂无总资产数据。")


# ── 持仓 ──


def _render_holdings():
    # 日期选择器
    all_dates = _available_dates()
    if not all_dates:
        st.info("暂无记录。")
        return

    selected_date = st.selectbox("选择日期", all_dates, key="portfolio_hdate")
    log = get_log_by_date(selected_date)
    if not log:
        return

    holdings = log.get("holdings") or []
    if not holdings:
        st.info(f"{selected_date} 无持仓记录。")
        return

    df = pd.DataFrame(holdings)
    # 重排列 + 重命名
    col_order = ["code", "name", "shares", "price", "pnl", "pnl_pct", "daily_pnl", "balance", "available"]
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]
    df.columns = [{"code": "代码", "name": "名称", "price": "市价", "pnl": "盈亏",
                    "daily_pnl": "当日盈亏", "pnl_pct": "盈亏比%", "shares": "数量",
                    "balance": "余额", "available": "可用"}.get(c, c) for c in df.columns]
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 合计行
    total_pnl = sum(h.get("pnl", 0) or 0 for h in holdings)
    total_daily = sum(h.get("daily_pnl", 0) or 0 for h in holdings)
    st.caption(f"持仓盈亏合计: {total_pnl:+,.2f}    当日盈亏合计: {total_daily:+,.2f}")


# ── 成交 ──


def _render_trades():
    all_dates = _available_dates()
    if not all_dates:
        st.info("暂无记录。")
        return

    selected_date = st.selectbox("选择日期", all_dates, key="portfolio_tdate")
    log = get_log_by_date(selected_date)
    if not log:
        return

    trades = log.get("trades") or []
    if not trades:
        st.info(f"{selected_date} 无成交记录。")
        return

    df = pd.DataFrame(trades)
    col_order = ["time", "code", "name", "action", "shares", "price", "amount", "contract_id", "trade_id"]
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]
    df.columns = [{"time": "时间", "code": "代码", "name": "名称", "action": "操作",
                    "shares": "数量", "price": "均价", "amount": "成交金额",
                    "contract_id": "合同编号", "trade_id": "成交编号"}.get(c, c) for c in df.columns]
    st.dataframe(df, use_container_width=True, hide_index=True)


# ── 录入 ──


def _render_entry():
    st.markdown("**录入日终快照**")

    today_str = datetime.now().strftime("%Y-%m-%d")

    with st.form("portfolio_entry", clear_on_submit=True):
        date = st.date_input("日期", value=None)
        date_str = date.strftime("%Y-%m-%d") if date else today_str

        st.markdown("**账户总览**")
        col1, col2, col3 = st.columns(3)
        with col1:
            total_assets = st.text_input("总资产", placeholder="如 1077215.90")
        with col2:
            market_value = st.text_input("总市值", placeholder="如 1076678.58")
        with col3:
            daily_pnl = st.text_input("当日盈亏", placeholder="如 15393.95")

        col1, col2, col3 = st.columns(3)
        with col1:
            total_pnl = st.text_input("总盈亏", placeholder="如 24748.78")
        with col2:
            cash_balance = st.text_input("资金余额", placeholder="如 1.92")
        with col3:
            withdrawable = st.text_input("可取金额", placeholder="如 1.92")

        available = st.text_input("可用金额", placeholder="如 1.92")

        st.markdown("**持仓列表**（每行一个 JSON 对象，整体为一个 JSON 数组）")
        holdings_text = st.text_area(
            "持仓 JSON",
            placeholder='[{"code": "603259", "name": "药明康德", "price": 124.12, "pnl": -20.32, ...}]',
            height=80,
        )

        st.markdown("**成交记录**（每行一个 JSON 对象，整体为一个 JSON 数组）")
        trades_text = st.text_area(
            "成交 JSON",
            placeholder='[{"time": "14:58:00", "code": "131810", "name": "R-001", ...}]',
            height=80,
        )

        submitted = st.form_submit_button("💾 保存", type="primary", use_container_width=True)

    if submitted:
        _save_entry(date_str, total_assets, market_value, total_pnl,
                    daily_pnl, cash_balance, withdrawable, available,
                    holdings_text, trades_text)


def _save_entry(date_str, total_assets, market_value, total_pnl,
                daily_pnl, cash_balance, withdrawable, available,
                holdings_text, trades_text):
    def _parse_float(v):
        if v is not None and v.strip():
            try:
                return float(v.replace(",", ""))
            except (ValueError, AttributeError):
                return None
        return None

    def _parse_json(v):
        if v and v.strip():
            try:
                parsed = json.loads(v.strip())
                if isinstance(parsed, list):
                    return parsed
                st.warning("JSON 应为数组格式 [...]")
                return None
            except json.JSONDecodeError:
                st.warning("JSON 解析失败，请检查格式")
                return None
        return None

    import json

    holdings = _parse_json(holdings_text)
    trades = _parse_json(trades_text)

    # 检查是否已有该日记录
    existing = get_log_by_date(date_str)

    if existing:
        # 已有 → 更新
        updates = {}
        for k, v in [("total_assets", _parse_float(total_assets)),
                     ("market_value", _parse_float(market_value)),
                     ("total_pnl", _parse_float(total_pnl)),
                     ("daily_pnl", _parse_float(daily_pnl)),
                     ("cash_balance", _parse_float(cash_balance)),
                     ("withdrawable", _parse_float(withdrawable)),
                     ("available", _parse_float(available))]:
            if v is not None:
                updates[k] = v
        if holdings is not None:
            updates["holdings"] = holdings
        if trades is not None:
            updates["trades"] = trades

        if updates:
            ok = update_log(existing["_id"], updates)
            if ok:
                st.success(f"✅ {date_str} 已更新")
                st.rerun()
            else:
                st.error("保存失败")
        else:
            st.info("没有需要更新的字段。")
    else:
        # 新建
        pid = create_log(
            date=date_str,
            total_assets=_parse_float(total_assets),
            market_value=_parse_float(market_value),
            total_pnl=_parse_float(total_pnl),
            daily_pnl=_parse_float(daily_pnl),
            cash_balance=_parse_float(cash_balance),
            withdrawable=_parse_float(withdrawable),
            available=_parse_float(available),
            holdings=holdings,
            trades=trades,
        )
        if pid:
            st.success(f"✅ {date_str} 已保存")
            st.rerun()
        else:
            st.error("保存失败")


# ── 辅助 ──


def _available_dates() -> list[str]:
    logs = list_logs(limit=365)
    return [log["date"] for log in logs if log.get("date")]
