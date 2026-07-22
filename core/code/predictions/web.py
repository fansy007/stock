"""Streamlit 预判复盘页面。

在 app.py 中引用：
    with _tabs[5]:
        from core.code.predictions.web import render_predictions
        render_predictions()
"""

import streamlit as st
from datetime import datetime, timezone, timedelta

from core.code.predictions.db import (
    list_predictions,
    get_prediction,
    update_prediction,
    create_prediction,
    delete_prediction,
    list_lesson_types,
)

_CONFIDENCE_OPTIONS = ["低", "中偏低", "中", "中偏高", "高", "信念"]
_RESULT_ICON = {
    "pending": "⏳",
    "correct": "✅",
    "wrong":   "❌",
    "expired": "⏰",
}
_RESULT_OPTIONS = {
    "pending": "⏳ 待验证",
    "correct": "✅ 正确",
    "wrong":   "❌ 错误",
    "expired": "⏰ 过期",
}

_ORIGINATOR_OPTIONS = ["海宁", "爱因斯坦", "共同"]

BEIJING = timezone(timedelta(hours=8))

# ── 过期判断 ──────────────────────────────────────


def _is_expired(p: dict) -> bool:
    dl = p.get("deadline")
    if dl and isinstance(dl, datetime):
        return dl.replace(tzinfo=None) < datetime.now()
    return False


def _fmt_dt(dt) -> str:
    if not isinstance(dt, datetime):
        return "—"
    # UTC → 北京时间
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    bj = dt.astimezone(BEIJING)
    return bj.strftime("%Y-%m-%d %H:%M")


# ── 渲染 ───────────────────────────────────────────


def render_predictions():
    st.markdown(
        "<h3 style='margin-bottom:0'>🔮 预判复盘</h3>"
        "<p style='color:#888;font-size:0.85rem;margin-top:-0.2rem'>"
        "记录 · 验证 · 积累经验</p>",
        unsafe_allow_html=True,
    )

    tab_labels = ["⏳ 待验证", "📁 已归档", "⭐ 精华", "➕ 新建"]
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        _render_pending()

    with tabs[1]:
        _render_archived()

    with tabs[2]:
        _render_featured()

    with tabs[3]:
        _render_new()


# ── 过滤器 ──────────────────────────────────────────


def _filter_controls(key_prefix: str) -> dict:
    col1, col2 = st.columns(2)
    with col1:
        tags_filter = st.text_input(
            "标签过滤", placeholder="输入标签名",
            key=f"{key_prefix}_tag_filter",
        )
    with col2:
        status_filter = st.multiselect(
            "结果状态",
            options=list(_RESULT_OPTIONS.keys()),
            format_func=lambda x: _RESULT_OPTIONS[x],
            default=None,
            key=f"{key_prefix}_status_filter",
        )
    return {"tags": tags_filter.strip(), "status": status_filter}


def _apply_filters(docs: list, filters: dict) -> list:
    tf = filters.get("tags", "")
    sf = filters.get("status", [])
    if sf:
        docs = [d for d in docs if d.get("result") in sf]
    if tf:
        docs = [d for d in docs
                if any(tf in t for t in (d.get("tags") or []))]
    return docs


# ── 子页面 ─────────────────────────────────────────


def _render_pending():
    filters = _filter_controls("pending")

    docs = list_predictions(result="pending", sort="-created_at")
    expired_docs = [d for d in docs if _is_expired(d)]
    active_docs = [d for d in docs if not _is_expired(d)]

    # 过期在前，再按更新时间降序
    ordered = expired_docs + active_docs
    ordered = _apply_filters(ordered, filters)

    st.markdown(f"**待验证 {len(ordered)} 条**（已过期 {len(expired_docs)}）")

    if not ordered:
        st.info("暂无待验证的预判")
        return

    for p in ordered:
        _render_card(p, is_expired=_is_expired(p), readonly=False, show_update_time=True)


def _render_archived():
    filters = _filter_controls("archived")

    docs = list_predictions(result=None, sort="-created_at")
    archived = [d for d in docs if d.get("result") in ("correct", "wrong", "expired")]
    archived = _apply_filters(archived, filters)

    if not archived:
        st.info("暂无已归档的预判")
        return

    c1 = sum(1 for d in archived if d.get("result") == "correct")
    w1 = sum(1 for d in archived if d.get("result") == "wrong")
    e1 = sum(1 for d in archived if d.get("result") == "expired")
    st.markdown(f"正确 {c1} · 错误 {w1} · 过期 {e1}")

    for p in archived:
        _render_card(p, readonly=False, show_update_time=True)


def _render_featured():
    docs = list_predictions(featured=True, sort="-created_at")
    st.markdown(f"**精华预判 & 经验** &nbsp;共 {len(docs)} 条")

    if not docs:
        st.info("暂无精华记录。编辑单条预判可标记为⭐精华。")
        return

    for p in docs:
        _render_card(p, readonly=False, show_update_time=True, tab="featured")


def _render_new():
    with st.form("new_prediction", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            target = st.text_input("主题 *", placeholder="如 菲利华中线走势")
        with col2:
            confidence = st.selectbox("置信度 *", _CONFIDENCE_OPTIONS, index=3)
        with col3:
            originator = st.selectbox("发起人", _ORIGINATOR_OPTIONS, index=0)

        judgment = st.text_area("预判内容 *", placeholder="一句可验证的判断", height=100)
        rationale = st.text_area("依据", placeholder="当时的判断逻辑", height=80)

        col1, col2 = st.columns(2)
        with col1:
            deadline = st.date_input("验证截止日（可选）", value=None)
        with col2:
            tags_str = st.text_input("标签（逗号分隔）", placeholder="菲利华, Q布")

        featured_new = st.checkbox("⭐ 标记为精华（精炼的经验/教训，长期有效）")

        submitted = st.form_submit_button("📝 记录预判", type="primary", use_container_width=True)

    if submitted:
        if not target.strip() or not judgment.strip():
            st.error("主题和预判内容为必填")
            return

        # 查历史教训
        history = list_predictions(result="wrong", target=target.strip())
        if history:
            lessons = [h for h in history if h.get("lesson")]
            if lessons:
                st.warning(f"⚠️ 该标的历史有 {len(lessons)} 条教训：")
                for h in lessons:
                    lt_name = ""
                    if h.get("lesson_type_id"):
                        lts = list_lesson_types()
                        for lt in lts:
                            if lt["_id"] == h["lesson_type_id"]:
                                lt_name = f"[{lt['name']}] "
                                break
                    st.caption(f"  {lt_name}{h['lesson']}")

        pid = create_prediction(
            judgment=judgment.strip(),
            target=target.strip(),
            confidence=confidence,
            originator=originator,
            rationale=rationale.strip() if rationale.strip() else "",
            deadline=datetime.combine(deadline, datetime.min.time()) if deadline else None,
            tags=[t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else [],
            featured=featured_new,
        )
        st.success(f"已记录 ✅  `{pid[:8]}...`")
        st.rerun()


# ── 卡片 ────────────────────────────────────────────


def _render_card(p: dict, readonly: bool = False, is_expired: bool = False, show_update_time: bool = False, tab: str = ""):
    pin_mark = "📌 " if p.get("pinned") else ""
    star_mark = "⭐ " if p.get("featured") else ""
    expired_mark = " ⚠️ 已过期" if is_expired else ""
    title = f"{pin_mark}{star_mark}{_RESULT_ICON.get(p.get('result'), '')} {p['target']}{expired_mark}"
    if show_update_time:
        ct = _fmt_dt(p.get("created_at"))
        title += f"  `{ct}`"

    with st.expander(title):
        _render_detail(p, tab=tab)


# ── 详情 ─────────────────────────────────────────────


def _render_detail(p: dict, tab: str = ""):
    kp = f"{tab}_" if tab else ""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"**置信度**  {p['confidence']}")
    with col2:
        st.markdown(f"**发起人**  {p['originator']}")
    with col3:
        dl = p.get("deadline")
        dl_str = _fmt_dt(dl) if dl else "—"
        st.markdown(f"**截止**  {dl_str}")
    with col4:
        tags = p.get("tags") or []
        st.markdown(f"**标签**  {', '.join(tags) if tags else '—'}")

    st.caption(f"创建 {_fmt_dt(p.get('created_at'))} · 更新 {_fmt_dt(p.get('updated_at'))}")

    st.markdown(f"**判断**  {p['judgment']}")
    if p.get("rationale"):
        st.markdown(f"**依据**  {p['rationale']}")

    # 已存在的复盘/教训（无论什么状态）
    if p.get("review"):
        st.markdown(f"**复盘**  {p['review']}")
    if p.get("lesson"):
        lt_name = ""
        lt_id = p.get("lesson_type_id")
        if lt_id:
            lts = list_lesson_types()
            for lt in lts:
                if lt["_id"] == lt_id:
                    lt_name = f"[{lt['name']}] "
                    break
        st.markdown(f"**教训**  {lt_name}{p['lesson']}")
    if p.get("superseded_by"):
        st.caption(f"↳ 已被新预判替代（{p['superseded_by'][:8]}...）")

    st.divider()

    # ── 操作按钮 ──
    edit_key = f"{kp}edit_{p['_id']}"
    delete_key = f"{kp}del_{p['_id']}"

    col_a, col_b, col_c, _ = st.columns([1, 1, 1, 5])
    # 置顶切换
    with col_a:
        is_pinned = p.get("pinned", False)
        pin_label = "📌 取消置顶" if is_pinned else "📌 置顶"
        if st.button(pin_label, key=f"{kp}pin_{p['_id']}", use_container_width=True):
            update_prediction(p["_id"], {"pinned": not is_pinned})
            st.rerun()
    with col_b:
        editing = st.session_state.get(edit_key, False)
        if st.button("✏️ 编辑", key=f"btn_{edit_key}", use_container_width=True):
            st.session_state[edit_key] = not editing
            st.rerun()
    with col_c:
        deleting = st.session_state.get(delete_key, False)
        if st.button("🗑️ 删除", key=f"btn_{delete_key}", use_container_width=True):
            st.session_state[delete_key] = not deleting
            st.rerun()

    # ── 删除确认 ──
    if st.session_state.get(delete_key, False):
        col_c, col_d = st.columns(2)
        with col_c:
            if st.button("确认删除", type="primary", key=f"confirm_{delete_key}", use_container_width=True):
                delete_prediction(p["_id"])
                st.session_state[delete_key] = False
                st.success("已删除")
                st.rerun()
        with col_d:
            if st.button("取消", key=f"cancel_{delete_key}", use_container_width=True):
                st.session_state[delete_key] = False
                st.rerun()

    # ── 编辑/验证表单 ──
    if st.session_state.get(edit_key, False):
        _render_edit_form(p, kp=kp)


def _render_edit_form(p: dict, kp: str = ""):
    """编辑字段：全部字段均可改。用 st.button 而非 st.form 避免回车提交。"""
    st.markdown("**编辑预判**")

    # 用 session_state 存储编辑中的字段值
    base = f"{kp}ef_{p['_id']}"
    if f"{base}_init" not in st.session_state:
        st.session_state[f"{base}_target"] = p.get("target", "")
        st.session_state[f"{base}_confidence"] = p["confidence"] if p["confidence"] in _CONFIDENCE_OPTIONS else "中"
        st.session_state[f"{base}_originator"] = p["originator"] if p["originator"] in _ORIGINATOR_OPTIONS else "海宁"
        st.session_state[f"{base}_judgment"] = p.get("judgment", "")
        st.session_state[f"{base}_rationale"] = p.get("rationale", "")
        st.session_state[f"{base}_deadline"] = p.get("deadline") if isinstance(p.get("deadline"), datetime) else None
        st.session_state[f"{base}_tags"] = ", ".join(p.get("tags") or [])
        st.session_state[f"{base}_result"] = p.get("result", "pending")
        st.session_state[f"{base}_review"] = p.get("review", "")
        st.session_state[f"{base}_lesson_type_id"] = p.get("lesson_type_id", "")
        st.session_state[f"{base}_lesson"] = p.get("lesson", "")
        st.session_state[f"{base}_featured"] = p.get("featured", False)
        st.session_state[f"{base}_init"] = True

    col1, col2, col3 = st.columns(3)
    with col1:
        st.text_input("主题", key=f"{base}_target")
    with col2:
        st.selectbox("置信度", _CONFIDENCE_OPTIONS, key=f"{base}_confidence")
    with col3:
        st.selectbox("发起人", _ORIGINATOR_OPTIONS, key=f"{base}_originator")

    st.text_area("预判内容", height=80, key=f"{base}_judgment")
    st.text_area("依据", height=60, key=f"{base}_rationale")

    col1, col2 = st.columns(2)
    with col1:
        dl = p.get("deadline")
        st.date_input("验证截止日", value=dl if isinstance(dl, datetime) else None, key=f"{base}_deadline")
    with col2:
        st.text_input("标签（逗号分隔）", key=f"{base}_tags")

    st.checkbox("⭐ 标记为精华", key=f"{base}_featured")

    st.selectbox(
        "结果",
        options=["pending", "correct", "wrong", "expired"],
        format_func=lambda x: _RESULT_OPTIONS[x],
        key=f"{base}_result",
    )

    st.text_area("复盘", height=60, key=f"{base}_review")

    lts = list_lesson_types()
    lt_opts = {lt["_id"]: lt["name"] for lt in lts}
    opts = [""] + list(lt_opts.keys())
    current = st.session_state.get(f"{base}_lesson_type_id", "")
    default_idx = 0
    if current in lt_opts:
        default_idx = opts.index(current)
    st.selectbox(
        "教训类型",
        options=opts,
        format_func=lambda x: lt_opts.get(x, "（无）") if x else "（无）",
        index=default_idx,
        key=f"{base}_lesson_type_id",
    )
    st.text_input("具体教训", key=f"{base}_lesson")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("💾 保存", type="primary", use_container_width=True, key=f"{base}_save"):
            lt_id = st.session_state.get(f"{base}_lesson_type_id", "")
            updates = {
                "target": st.session_state[f"{base}_target"].strip(),
                "judgment": st.session_state[f"{base}_judgment"].strip(),
                "confidence": st.session_state[f"{base}_confidence"],
                "originator": st.session_state[f"{base}_originator"],
                "rationale": st.session_state[f"{base}_rationale"].strip(),
                "result": st.session_state[f"{base}_result"],
                "review": st.session_state[f"{base}_review"].strip(),
                "lesson": st.session_state[f"{base}_lesson"].strip(),
                "lesson_type_id": lt_id if lt_id else None,
                "tags": [t.strip() for t in st.session_state[f"{base}_tags"].split(",") if t.strip()] if st.session_state[f"{base}_tags"].strip() else [],
                "featured": st.session_state[f"{base}_featured"],
            }
            dl = st.session_state.get(f"{base}_deadline")
            updates["deadline"] = dl if isinstance(dl, datetime) else None

            ok = update_prediction(p["_id"], updates)
            if ok:
                # 清理编辑状态
                for k in list(st.session_state.keys()):
                    if k.startswith(f"{base}_"):
                        del st.session_state[k]
                st.session_state[f"{kp}edit_{p['_id']}"] = False
                st.success("已保存")
                st.rerun()
            else:
                st.error("保存失败")
    with col_b:
        if st.button("取消", key=f"{base}_cancel", use_container_width=True):
            for k in list(st.session_state.keys()):
                if k.startswith(f"{base}_"):
                    del st.session_state[k]
            st.session_state[f"{kp}edit_{p['_id']}"] = False
            st.rerun()
