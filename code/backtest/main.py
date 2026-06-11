"""
回测系统入口

用法:
    python -m code.backtest.main                      # 使用默认配置
    python -m code.backtest.main --config path/to/config.json

配置示例见 config/ 目录下的 JSON 文件。
"""
import sys
import os
import argparse

# 确保项目根目录在路径中
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from code.backtest.engine import BacktestEngine
from code.backtest.metrics import print_report, calc_metrics, save_results, plot_curve


def main():
    parser = argparse.ArgumentParser(description='回测系统')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='回测配置文件路径')
    parser.add_argument('--no-plot', action='store_true',
                        help='不生成图表')
    args = parser.parse_args()

    # 创建引擎并运行
    engine = BacktestEngine(config_path=args.config)

    try:
        result = engine.run()
    except RuntimeError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    # 报告
    metrics = calc_metrics(result)
    print_report(result, metrics)

    # 保存
    save_results(result)

    # 绘图
    if not args.no_plot:
        plot_curve(result)


if __name__ == '__main__':
    main()
