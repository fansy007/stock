"""
Streamlit 回测页面

在 app.py 中作为第4个 tab 引用：
    with _tabs[3]:
        from code.backtest.web import render_backtest_page
        render_backtest_page()
"""

import os
import json
import streamlit as st
import pandas as pd

from code.backtest.config_manager import (
    list_sets, load_set, save_set, delete_set,
    create_from_template, rename_set,
)


def render_backtest_page():
    """渲染回测页面"""

    # ── 状态初始化 ──
    if 'bt_current_set' not in st.session_state:
        st.session_state.bt_current_set = None  # (name, kind)
    if 'bt_configs' not in st.session_state:
        st.session_state.bt_configs = None
    if 'bt_result' not in st.session_state:
        st.session_state.bt_result = None
    if 'bt_running' not in st.session_state:
        st.session_state.bt_running = False
    if 'bt_editor_tab' not in st.session_state:
        st.session_state.bt_editor_tab = 0
    if 'bt_show_new_dialog' not in st.session_state:
        st.session_state.bt_show_new_dialog = False
    if 'bt_show_rename_dialog' not in st.session_state:
        st.session_state.bt_show_rename_dialog = False
    if 'bt_show_delete_confirm' not in st.session_state:
        st.session_state.bt_show_delete_confirm = False
    if 'bt_realtime_result' not in st.session_state:
        st.session_state.bt_realtime_result = None
    if 'bt_realtime_running' not in st.session_state:
        st.session_state.bt_realtime_running = False

    # ── 布局：左侧组合列表 · 右侧编辑器+结果 ──
    left, right = st.columns([0.28, 0.72])

    # ================================================================
    # 左侧：组合列表
    # ================================================================
    with left:
        st.markdown("##### 配置组合")
        all_sets = list_sets()

        # 按类型分组显示
        default_sets = [(n, k) for n, k in all_sets if k == 'default']
        custom_sets = [(n, k) for n, k in all_sets if k == 'custom']

        selected = st.session_state.bt_current_set

        # 系统模板
        if default_sets:
            st.caption("系统模板")
            for name, kind in default_sets:
                active = (selected == (name, kind))
                if st.button(
                    f"{'📄' if active else '  '} {name}",
                    key=f"bt_load_{kind}_{name}",
                    use_container_width=True,
                    type="primary" if active else "secondary",
                ):
                    st.session_state.bt_current_set = (name, kind)
                    st.session_state.bt_configs = load_set(name, kind)
                    st.session_state.bt_result = None
                    st.rerun()

        # 用户自定义
        if custom_sets:
            st.caption("我的组合")
            for name, kind in custom_sets:
                active = (selected == (name, kind))
                if st.button(
                    f"{'📄' if active else '  '} {name}",
                    key=f"bt_load_{kind}_{name}",
                    use_container_width=True,
                    type="primary" if active else "secondary",
                ):
                    st.session_state.bt_current_set = (name, kind)
                    st.session_state.bt_configs = load_set(name, kind)
                    st.session_state.bt_result = None
                    st.rerun()

        # ── 新建 ──
        if st.button("➕ 新建组合", use_container_width=True, key="bt_new"):
            st.session_state.bt_show_new_dialog = True
            st.rerun()

        if st.session_state.bt_show_new_dialog:
            with st.container(border=True):
                new_name = st.text_input("组合名称", key="bt_new_name", placeholder="如 创业板因子v2")
                if default_sets:
                    tmpl = st.selectbox("从模板", [n for n, k in default_sets], key="bt_new_tmpl")
                else:
                    tmpl = None
                    st.info("无可用模板")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("创建", key="bt_new_confirm", use_container_width=True):
                        if new_name.strip():
                            try:
                                if tmpl:
                                    create_from_template(new_name.strip(), tmpl)
                                else:
                                    save_set(new_name.strip(), {
                                        'backtest': {},
                                        'buy': {},
                                        'sell': {}
                                    })
                                st.session_state.bt_current_set = (new_name.strip(), 'custom')
                                st.session_state.bt_configs = load_set(new_name.strip(), 'custom')
                                st.session_state.bt_show_new_dialog = False
                                st.rerun()
                            except FileExistsError:
                                st.error(f"组合 '{new_name}' 已存在")
                        else:
                            st.warning("请输入名称")
                with c2:
                    if st.button("取消", key="bt_new_cancel", use_container_width=True):
                        st.session_state.bt_show_new_dialog = False
                        st.rerun()

        # ── 对当前自定义组合的操作 ──
        if selected and selected[1] == 'custom':
            st.divider()
            st.caption(f"当前: {selected[0]}")

            if st.button("✏️ 重命名", use_container_width=True, key="bt_rename_btn"):
                st.session_state.bt_show_rename_dialog = True
                st.rerun()

            if st.session_state.bt_show_rename_dialog:
                new_name = st.text_input("新名称", value=selected[0], key="bt_rename_input")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("确认", key="bt_rename_confirm", use_container_width=True):
                        if new_name.strip() and new_name.strip() != selected[0]:
                            try:
                                rename_set(selected[0], new_name.strip())
                                st.session_state.bt_current_set = (new_name.strip(), 'custom')
                                st.session_state.bt_show_rename_dialog = False
                                st.rerun()
                            except FileExistsError:
                                st.error(f"名称 '{new_name}' 已存在")
                        else:
                            st.session_state.bt_show_rename_dialog = False
                            st.rerun()
                with c2:
                    if st.button("取消", key="bt_rename_cancel", use_container_width=True):
                        st.session_state.bt_show_rename_dialog = False
                        st.rerun()

            if st.button("🗑️ 删除", use_container_width=True, key="bt_delete_btn"):
                st.session_state.bt_show_delete_confirm = True
                st.rerun()

            if st.session_state.bt_show_delete_confirm:
                st.warning(f"确认删除 '{selected[0]}'？")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("确认删除", key="bt_delete_confirm", use_container_width=True):
                        delete_set(selected[0])
                        st.session_state.bt_current_set = None
                        st.session_state.bt_configs = None
                        st.session_state.bt_show_delete_confirm = False
                        st.rerun()
                with c2:
                    if st.button("取消", key="bt_delete_cancel", use_container_width=True):
                        st.session_state.bt_show_delete_confirm = False
                        st.rerun()

    # ================================================================
    # 右侧：编辑器 + 结果
    # ================================================================
    with right:
        configs = st.session_state.bt_configs
        current_set = st.session_state.bt_current_set

        if configs is None:
            st.info("← 从左侧选择一个配置组合")
            return

        # ── 标签页选择 ──
        tab_names = ["📋 回测配置", "📥 买入策略", "📤 卖出策略"]
        tab_idx = st.session_state.bt_editor_tab
        chosen_tab = st.radio(
            "配置标签",
            tab_names,
            index=tab_idx,
            horizontal=True,
            label_visibility="collapsed",
            key="bt_editor_radio",
        )
        st.session_state.bt_editor_tab = tab_names.index(chosen_tab)

        # ── 编辑区 ──
        set_name, set_kind = current_set
        is_readonly = (set_kind == 'default')

        config_key_map = {
            "📋 回测配置": 'backtest',
            "📥 买入策略": 'buy',
            "📤 卖出策略": 'sell',
        }
        key = config_key_map[chosen_tab]
        current = configs.get(key, {})

        try:
            text = json.dumps(current, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = "{}"

        edited = st.text_area(
            f"{chosen_tab} {'（只读预览）' if is_readonly else ''}",
            value=text,
            height=400,
            key=f"bt_editor_{key}",
            disabled=is_readonly,
        )

        # ── 操作按钮 ──
        col_save, col_run, col_status = st.columns([1, 1, 2])

        with col_save:
            if not is_readonly:
                if st.button("💾 保存配置", use_container_width=True, key="bt_save"):
                    try:
                        parsed = json.loads(edited)
                        configs[key] = parsed
                        save_set(set_name, configs)
                        st.success(f"已保存到 custom/{set_name}/")
                    except json.JSONDecodeError as e:
                        st.error(f"JSON 格式错误: {e}")

        with col_run:
            if st.button("▶️ 运行回测", type="primary", use_container_width=True, key="bt_run"):
                # 先保存当前编辑
                try:
                    parsed = json.loads(edited)
                    configs[key] = parsed
                    if not is_readonly:
                        save_set(set_name, configs)
                except json.JSONDecodeError:
                    st.error("当前 tab JSON 格式不对，修正后再跑")
                    st.stop()

                # 写临时配置文件跑回测
                import tempfile
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.json', delete=False, encoding='utf-8'
                ) as f:
                    json.dump(configs['backtest'], f, ensure_ascii=False)
                    tmp_path = f.name

                st.session_state.bt_running = True
                try:
                    from code.backtest.engine import BacktestEngine
                    from code.backtest.metrics import calc_metrics, print_report
                    from io import StringIO
                    import sys

                    # 重定向 print 输出
                    old_stdout = sys.stdout
                    sys.stdout = StringIO()

                    engine = BacktestEngine(tmp_path)
                    engine._load_strategies()

                    # 传买入和卖出配置
                    buy_cfg = configs.get('buy', {})
                    sell_cfg = configs.get('sell', {})
                    if hasattr(engine.buy_strategy, '_config'):
                        engine.buy_strategy._config = buy_cfg
                    if hasattr(engine.sell_strategy, '_config'):
                        engine.sell_strategy._config = sell_cfg

                    result = engine.run()
                    metrics = calc_metrics(result)
                    log = sys.stdout.getvalue()
                    sys.stdout = old_stdout

                    # 保存到 session
                    st.session_state.bt_result = {
                        'result': result,
                        'metrics': metrics,
                        'log': log,
                    }
                    st.rerun()

                except Exception as e:
                    sys.stdout = old_stdout
                    st.error(f"回测失败: {e}")
                finally:
                    os.unlink(tmp_path)
                    st.session_state.bt_running = False

        with col_status:
            if st.session_state.bt_running:
                st.info("⏳ 运行中...")

        # 如果系统模板被编辑了但不保存，提醒
        if is_readonly and edited != text:
            st.caption("⚠️ 系统模板为只读。如需修改请「新建组合」从模板复制。")

        # ================================================================
        # 实时选股
        # ================================================================
        st.divider()
        st.markdown("##### 📡 实时选股")

        rt_col1, rt_col2 = st.columns([2, 1])
        with rt_col1:
            rt_date = st.text_input(
                "选股日期", value="20260529",
                key="bt_realtime_date",
                help="格式 YYYYMMDD，如 20260529",
            )
        with rt_col2:
            rt_go = st.button("🔍 选股", type="primary",
                              use_container_width=True, key="bt_realtime_go")

        # 按钮触发 → 存日期，设运行标志，rerun
        if rt_go:
            st.session_state.bt_realtime_pending = rt_date.strip()
            st.session_state.bt_realtime_running = True
            st.rerun()

        # 执行选股（在带 running 标志的 rerun 中）
        if st.session_state.bt_realtime_running:
            pick_date = st.session_state.bt_realtime_pending
            try:
                from code.backtest.strategy.protocol import load_buy_strategy
                from io import StringIO
                import sys

                # 从当前配置读取买入策略名
                strat_name = configs.get('backtest', {}).get('strategies', {}).get('buy', 'buy_factor_strategy')
                buy_cfg = configs.get('buy', {})

                old_stdout = sys.stdout
                sys.stdout = StringIO()

                print(f"  买入策略: {strat_name}")
                strat = load_buy_strategy(strat_name)
                strat._config = buy_cfg

                result = strat.select(pick_date)
                log = sys.stdout.getvalue()
                sys.stdout = old_stdout

                st.session_state.bt_realtime_result = {
                    'stocks': result.stocks,
                    'prices': result.prices,
                    'scores': result.scores,
                    'log': log,
                    'date': pick_date,
                }
                st.session_state.bt_realtime_running = False
                st.rerun()

            except Exception as e:
                sys.stdout = old_stdout
                st.session_state.bt_realtime_running = False
                st.error(f"实时选股失败: {e}")

        # 显示结果
        rt_result = st.session_state.bt_realtime_result
        if rt_result and not st.session_state.bt_realtime_running:
            with st.expander("📝 选股日志", expanded=False):
                st.text(rt_result.get('log', ''))

            stocks = rt_result.get('stocks', [])
            prices = rt_result.get('prices', {})
            pick_date = rt_result.get('date', '')

            if stocks:
                scores = rt_result.get('scores', {})
                rows = []
                for i, s in enumerate(stocks):
                    rows.append({
                        '序号': i + 1,
                        '股票': s,
                        '评分': f"{scores.get(s, 0):.2f}" if scores else '',
                        '价格': f"{prices.get(s, 0):.2f}" if prices else '',
                    })
                df = pd.DataFrame(rows)
                st.dataframe(df, hide_index=True, use_container_width=True)
            else:
                st.info(f"{pick_date} 未选出股票")

        # ================================================================
        # 回测结果区域
        # ================================================================
        bt_data = st.session_state.bt_result
        if bt_data:
            st.divider()
            st.markdown("##### 📊 回测结果")

            result = bt_data['result']
            metrics = bt_data['metrics']
            log = bt_data['log']

            with st.expander("📝 运行日志", expanded=False):
                st.text(log)

            # 指标卡片
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("总收益", f"{metrics.total_return:+.2f}%")
            m2.metric("年化", f"{metrics.annual_return:+.2f}%")
            m3.metric("最大回撤", f"{metrics.max_drawdown:.2f}%")
            m4.metric("夏普比率", f"{metrics.sharpe:.2f}")
            m5.metric("交易次数", str(metrics.total_trades))

            m6, m7, m8, m9 = st.columns(4)
            m6.metric("胜率", f"{metrics.win_rate:.1f}%")
            m7.metric("盈亏比", f"{metrics.profit_loss_ratio:.2f}")
            m8.metric("初始资金", f"{result.initial_capital:,.0f}")
            m9.metric("最终资产", f"{result.final_value:,.0f}")

            # 资产曲线
            try:
                _plot_curve(result)
            except Exception:
                pass

            # 交易明细
            with st.expander("📋 交易明细", expanded=False):
                if result.trades:
                    rows = []
                    for t in result.trades:
                        rows.append({
                            '日期': t.date,
                            '股票': t.stock,
                            '方向': t.action,
                            '价格': f"{t.price:.2f}",
                            '数量': t.shares,
                            '金额': f"{t.cost:.0f}",
                            '盈亏': f"{t.profit:+.0f}" if t.action == 'SELL' else '',
                            '原因': t.reason if t.action == 'SELL' else '',
                        })
                    df = pd.DataFrame(rows)
                    st.dataframe(df, hide_index=True, use_container_width=True)

            # 每日资产
            with st.expander("📈 每日资产", expanded=False):
                if result.daily_assets:
                    rows = []
                    for a in result.daily_assets:
                        rows.append({
                            '日期': a.date,
                            '现金': f"{a.cash:,.0f}",
                            '市值': f"{a.stock_value:,.0f}",
                            '总资产': f"{a.total_value:,.0f}",
                            '持仓': a.positions,
                        })
                    df = pd.DataFrame(rows)
                    st.dataframe(df, hide_index=True, use_container_width=True)


def _plot_curve(result):
    """绘制累计收益率曲线（出发点=0%）"""
    import pandas as pd
    from code.backtest.engine import DailyAsset

    init = result.initial_capital
    data = {'date': []}
    strat_col = []
    bm_col = []

    for a in result.daily_assets:
        data['date'].append(pd.Timestamp(a.date))
        strat_col.append((a.total_value / init - 1) * 100)
        bm_col.append((a.benchmark_value / init - 1) * 100)

    data['策略'] = strat_col
    if result.benchmark_available:
        data['基准'] = bm_col

    df = pd.DataFrame(data).set_index('date')
    st.line_chart(df, use_container_width=True)
