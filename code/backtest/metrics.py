"""
绩效指标计算

计算年化收益率、最大回撤、夏普比率、胜率、盈亏比等。
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from .engine import BacktestResult, TradeRecord, DailyAsset


@dataclass
class Metrics:
    """绩效指标"""
    annual_return: float = 0.0
    annual_vol: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_date: str = ''
    drawdown_duration: int = 0
    sharpe: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_trades: int = 0
    total_return: float = 0.0


def calc_metrics(result: BacktestResult) -> Metrics:
    """从回测结果计算绩效指标

    Args:
        result: BacktestResult

    Returns:
        Metrics dataclass
    """
    metrics = Metrics()
    assets = result.daily_assets
    trades = result.trades
    initial = result.initial_capital

    if not assets:
        return metrics

    df = pd.DataFrame([{
        'date': a.date,
        'total_value': a.total_value,
        'benchmark_value': a.benchmark_value
    } for a in assets])
    df['date'] = pd.to_datetime(df['date'])

    # 总收益
    final_value = df['total_value'].iloc[-1]
    total_return = (final_value - initial) / initial * 100
    metrics.total_return = total_return

    # 日收益率
    df['daily_return'] = df['total_value'].pct_change().fillna(0)

    # 年化收益率
    trading_days = len(df)
    if trading_days > 0:
        annual_ret = (1 + total_return / 100) ** (252 / trading_days) - 1
        metrics.annual_return = annual_ret * 100

    # 年化波动率
    daily_std = df['daily_return'].std()
    metrics.annual_vol = daily_std * np.sqrt(252) * 100

    # 最大回撤
    cummax = df['total_value'].cummax()
    drawdown = (df['total_value'] - cummax) / cummax
    max_dd = drawdown.min()
    metrics.max_drawdown = max_dd * 100

    if max_dd < 0:
        max_dd_idx = drawdown.idxmin()
        metrics.max_drawdown_date = df.loc[max_dd_idx, 'date'].strftime('%Y%m%d')

        # 回撤持续时间
        peak_before = df.loc[:max_dd_idx, 'total_value'].idxmax()
        peak_date = df.loc[peak_before, 'date']
        metrics.drawdown_duration = (df.loc[max_dd_idx, 'date'] - peak_date).days

    # 夏普比率
    excess = df['daily_return'] - 0  # 无风险利率假设为0
    if daily_std > 0:
        metrics.sharpe = (annual_ret or 0) / (daily_std * np.sqrt(252))

    # 交易统计
    sell_trades = [t for t in trades if t.action == 'SELL' and t.reason != '结束平仓']
    metrics.total_trades = len(sell_trades)

    if sell_trades:
        profits = [t.profit for t in sell_trades]
        win = [p for p in profits if p > 0]
        loss = [p for p in profits if p <= 0]

        metrics.win_rate = len(win) / len(sell_trades) * 100 if sell_trades else 0

        avg_win = sum(win) / len(win) if win else 0
        avg_loss = abs(sum(loss) / len(loss)) if loss else 0
        metrics.profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    return metrics


def print_report(result: BacktestResult, metrics: Metrics = None):
    """打印回测报告"""
    if metrics is None:
        metrics = calc_metrics(result)

    initial = result.initial_capital
    final = result.final_value

    print("\n" + "=" * 60)
    print("  回测报告")
    print("=" * 60)

    print(f"\n【资金】")
    print(f"  初始: {initial:>12,.0f}")
    print(f"  最终: {final:>12,.0f}")
    print(f"  收益: {final - initial:>12,.0f}  ({metrics.total_return:+.2f}%)")

    print(f"\n【交易统计】")
    buys = [t for t in result.trades if t.action == 'BUY']
    sells = [t for t in result.trades if t.action == 'SELL' and t.reason != '结束平仓']
    print(f"  买入: {len(buys)} 次")
    print(f"  卖出: {len(sells)} 次")
    print(f"  胜率: {metrics.win_rate:.1f}%")
    print(f"  盈亏比: {metrics.profit_loss_ratio:.2f}")

    if sells:
        win_trades = [t for t in sells if t.profit > 0]
        loss_trades = [t for t in sells if t.profit <= 0]

        if win_trades:
            print(f"\n  TOP5盈利:")
            for t in sorted(win_trades, key=lambda x: x.profit, reverse=True)[:5]:
                print(f"    {t.stock}  {t.date}  +{t.profit:>8,.0f}  {t.reason}")

        if loss_trades:
            print(f"\n  TOP5亏损:")
            for t in sorted(loss_trades, key=lambda x: x.profit)[:5]:
                print(f"    {t.stock}  {t.date}  {t.profit:>8,.0f}  {t.reason}")

    print(f"\n【风险指标】")
    print(f"  年化收益率: {metrics.annual_return:+.2f}%")
    print(f"  年化波动率: {metrics.annual_vol:.2f}%")
    print(f"  最大回撤: {metrics.max_drawdown:.2f}%")
    print(f"  最大回撤日期: {metrics.max_drawdown_date} ({metrics.drawdown_duration}天)")
    print(f"  夏普比率: {metrics.sharpe:.2f}")

    # 基准对比
    if result.daily_assets:
        first_bm = result.daily_assets[0].benchmark_value
        last_bm = result.daily_assets[-1].benchmark_value
        if first_bm and last_bm:
            bm_return = (last_bm - first_bm) / first_bm * 100
            print(f"\n【基准对比】")
            print(f"  基准收益: {bm_return:+.2f}%")
            print(f"  超额收益: {metrics.total_return - bm_return:+.2f}%")

    print()


def save_results(result: BacktestResult, output_dir: str = None):
    """保存回测结果到 CSV"""
    import os

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)

    # 交易记录
    if result.trades:
        df = pd.DataFrame([{
            'date': t.date, 'stock': t.stock, 'action': t.action,
            'price': t.price, 'shares': t.shares, 'cost': t.cost,
            'profit': t.profit, 'reason': t.reason, 'pnl_pct': t.pnl_pct
        } for t in result.trades])
        df.to_csv(os.path.join(output_dir, 'backtest_trades.csv'),
                  index=False, encoding='utf-8-sig')

    # 每日资产
    if result.daily_assets:
        df = pd.DataFrame([{
            'date': a.date, 'cash': a.cash,
            'stock_value': a.stock_value, 'total_value': a.total_value,
            'positions': a.positions, 'benchmark_value': a.benchmark_value
        } for a in result.daily_assets])
        df.to_csv(os.path.join(output_dir, 'backtest_assets.csv'),
                  index=False, encoding='utf-8-sig')

    print(f"[报告] 结果已保存到 {output_dir}")


def plot_curve(result: BacktestResult, output_dir: str = None):
    """绘制资产曲线"""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(__file__), 'output')
        os.makedirs(output_dir, exist_ok=True)

        df = pd.DataFrame([{
            'date': pd.Timestamp(a.date),
            'total_value': a.total_value,
            'benchmark_value': a.benchmark_value,
        } for a in result.daily_assets])

        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(df['date'], df['total_value'], 'b-',
                linewidth=1.5, label='Strategy')
        ax.plot(df['date'], df['benchmark_value'], 'r--',
                linewidth=1.5, label='Benchmark')
        ax.axhline(y=result.initial_capital, color='gray',
                   linestyle='--', alpha=0.5, label='Initial')

        ax.set_title('Backtest - Asset Curve', fontsize=14)
        ax.set_xlabel('Date')
        ax.set_ylabel('Value')
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        plt.tight_layout()

        fp = os.path.join(output_dir, 'backtest_curve.png')
        plt.savefig(fp, dpi=150)
        plt.close()
        print(f"[报告] 资产曲线已保存: {fp}")
    except ImportError:
        print("[报告] matplotlib 未安装，跳过绘图")
    except Exception as e:
        print(f"[报告] 绘图失败: {e}")
