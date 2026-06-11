"""
回测系统

目录结构:
    engine.py           回测引擎主循环
    metrics.py          绩效指标计算 + 报告输出
    data/loader.py      K线数据加载
    strategy/           买卖策略（含命名规则 *strategy*.py）
    config/             配置文件（JSON 格式）
"""
