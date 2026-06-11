"""
回测引擎

主循环：每日遍历交易日 → 调仓日选股 → 卖出 → 买入 → 记录资产。
数据一次性加载到内存，不复查文件。
"""
import os
import json
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from datetime import datetime, timedelta
from .data.loader import load_kline_data, get_trading_dates, load_stock_list, _default_kline_dir
from .strategy.protocol import (BaseBuyStrategy, BaseSellStrategy,
                                load_buy_strategy, load_sell_strategy,
                                BuyResult, SellSignal)

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config', 'backtest.json')


def load_config(path: str = None) -> dict:
    path = path or DEFAULT_CONFIG_PATH
    defaults = {
        "capital": {
            "initial": 1000000,
            "min_buy": 50000,
            "commission_rate": 0.0003,
            "stamp_tax_rate": 0.001,
            "slippage": 0.001
        },
        "period": {
            "start": "20260401",
            "end": "20260507"
        },
        "portfolio": {
            "max_positions": 20,
            "position_sizing": "equal_weight"
        },
        "benchmark": "399006.SZ",
        "strategies": {
            "buy": "buy_factor_strategy",
            "sell": "sell_trailing_strategy"
        },
        "rebalance_days": 0
    }
    if not os.path.exists(path):
        print(f"[引擎] 配置文件不存在: {path}，使用默认配置")
        return defaults
    with open(path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)
        # 深层合并
        for key, val in loaded.items():
            if key in defaults and isinstance(val, dict) and isinstance(defaults[key], dict):
                defaults[key].update(val)
            else:
                defaults[key] = val
        return defaults


@dataclass
class Position:
    """持仓记录"""
    shares: int = 0
    cost: float = 0.0
    buy_date: str = ''
    peak_price: float = 0.0


@dataclass
class TradeRecord:
    """交易记录"""
    date: str = ''
    stock: str = ''
    action: str = ''      # BUY / SELL
    price: float = 0.0
    shares: int = 0
    cost: float = 0.0
    profit: float = 0.0
    reason: str = ''
    pnl_pct: float = 0.0
    cash_before: float = 0.0
    cash_after: float = 0.0


@dataclass
class DailyAsset:
    """每日资产快照"""
    date: str = ''
    cash: float = 0.0
    stock_value: float = 0.0
    total_value: float = 0.0
    positions: int = 0
    benchmark_value: float = 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    trades: list = field(default_factory=list)
    daily_assets: list = field(default_factory=list)
    config: dict = field(default_factory=dict)
    initial_capital: float = 0
    final_value: float = 0
    benchmark_available: bool = False


class BacktestEngine:
    """回测引擎"""

    def __init__(self, config_path: str = None):
        self.config = load_config(config_path)
        self.capital_cfg = self.config.get('capital', {})
        self.period_cfg = self.config.get('period', {})
        self.portfolio_cfg = self.config.get('portfolio', {})

        self.initial_capital = self.capital_cfg.get('initial', 1000000)
        self.min_buy = self.capital_cfg.get('min_buy', 50000)
        self.commission = self.capital_cfg.get('commission_rate', 0.0003)
        self.stamp_tax = self.capital_cfg.get('stamp_tax_rate', 0.001)
        self.slippage = self.capital_cfg.get('slippage', 0.001)

        self.start_date = self.period_cfg.get('start', '20240101')
        self.end_date = self.period_cfg.get('end', '20250601')
        self.benchmark_code = self.config.get('benchmark', '399006.SZ')
        self.max_positions = self.portfolio_cfg.get('max_positions', 20)
        self.rebalance_days = self.config.get('rebalance_days', 0)

        # 状态
        self.cash = self.initial_capital
        self.positions = {}    # {stock: Position}
        self.trades = []
        self.daily_assets = []

        # 数据
        self.kline_data = None
        self.trading_dates = []
        self.benchmark_prices = {}

        # 策略
        self.buy_strategy: Optional[BaseBuyStrategy] = None
        self.sell_strategy: Optional[BaseSellStrategy] = None

    def set_buy_strategy(self, strategy: BaseBuyStrategy):
        self.buy_strategy = strategy

    def set_sell_strategy(self, strategy: BaseSellStrategy):
        self.sell_strategy = strategy

    def _load_strategies(self):
        """根据 config 加载策略"""
        strategies = self.config.get('strategies', {})
        buy_name = strategies.get('buy', 'buy_factor_strategy')
        sell_name = strategies.get('sell', 'sell_trailing_strategy')

        if self.buy_strategy is None:
            print(f"[引擎] 加载买入策略: {buy_name}")
            self.buy_strategy = load_buy_strategy(buy_name)
        if self.sell_strategy is None:
            print(f"[引擎] 加载卖出策略: {sell_name}")
            self.sell_strategy = load_sell_strategy(sell_name)

    def _get_history_buffer_days(self) -> int:
        """从配置文件读取历史缓冲天数，默认 180

        策略可以在 backtest.json 中设置 history_buffer_days 来自定义需要的
        历史数据量。例如长期下跌企稳策略需要 500+ 天的数据来计算 250 日最高点。

        设为 0 则加载全部可用数据（CSV 里有多少天就加载多少天）。
        """
        return int(self.config.get('history_buffer_days', 180))

    def _load_data(self):
        """加载 K 线数据和交易日历

        回测期间从 start_date 开始，但数据加载会往前多拉 history_buffer_days
        天，供因子计算使用。默认 180 天，可在配置文件中覆盖。
        设为 0 则全部加载。
        """
        # K线目录
        self.kline_dir = _default_kline_dir()

        # 计算带缓冲的起始日期
        start_dt = datetime.strptime(self.start_date, '%Y%m%d')
        buffer_days = self._get_history_buffer_days()
        if buffer_days <= 0:
            # 0 = 全部加载，用最小日期确保 CSV 全部读入
            buffer_start = datetime(2000, 1, 1)
        else:
            buffer_start = (start_dt - timedelta(days=buffer_days))

        # 获取股票池（从买入策略或全量）
        stock_pool = None
        if self.buy_strategy:
            buy_config = self.buy_strategy.load_config()
            pool_cfg = buy_config.get('stock_pool', {})
            if pool_cfg.get('source') == 'list':
                stock_pool = pool_cfg.get('list', [])

        if not stock_pool:
            stock_pool = load_stock_list()

        print(f"[引擎] 股票池: {len(stock_pool)} 只")

        # 加载 K 线（用缓冲起始日期，确保因子有足够历史数据）
        self.kline_data = load_kline_data(
            stock_pool,
            buffer_start.strftime('%Y%m%d'),
            self.end_date)

        if self.kline_data.empty:
            raise RuntimeError("无法加载K线数据，回测终止")

        print(f"[引擎] K线数据范围: "
              f"{self.kline_data.index.get_level_values('date').min().strftime('%Y%m%d')} ~ "
              f"{self.kline_data.index.get_level_values('date').max().strftime('%Y%m%d')}")

        # 获取交易日历（只用实际回测期间）
        self.trading_dates = get_trading_dates(self.start_date, self.end_date)
        print(f"[引擎] 交易日: {len(self.trading_dates)} 天")

        # 基准价格
        self.benchmark_available = False
        self._load_benchmark()

    def _load_benchmark(self):
        """加载基准价格"""
        if self.kline_data is None or self.kline_data.empty:
            return

        # 尝试用 config 指定的基准
        try:
            bm_data = self.kline_data.xs(self.benchmark_code, level='symbol')
            self.benchmark_prices = bm_data['close'].to_dict()
            print(f"[引擎] 基准: {self.benchmark_code}, {len(self.benchmark_prices)} 天")
            self.benchmark_available = True
            return
        except KeyError:
            pass

        # 尝试单独加载基准CSV（指数如 399006.SZ 可能不在股票池里）
        bm_csv_path = os.path.join(self.kline_dir, f'{self.benchmark_code}.csv')
        if os.path.exists(bm_csv_path):
            try:
                bm_df = pd.read_csv(bm_csv_path)
                bm_df['date'] = pd.to_datetime(bm_df['time'], unit='ms').dt.normalize()
                # 只取回测期间
                start = pd.Timestamp(self.start_date)
                end = pd.Timestamp(self.end_date) + pd.Timedelta(days=1)
                bm_df = bm_df[(bm_df['date'] >= start) & (bm_df['date'] < end)]
                if not bm_df.empty:
                    self.benchmark_prices = dict(zip(
                        bm_df['date'].dt.strftime('%Y%m%d'), bm_df['close']))
                    print(f"[引擎] 基准从CSV加载: {self.benchmark_code}, {len(self.benchmark_prices)} 天")
                    self.benchmark_available = True
                    return
            except Exception as e:
                print(f"[引擎] 基准CSV读取失败: {e}")

        # 不可用 — 后续图表不再画基准线
        print(f"[引擎] 基准 {self.benchmark_code} 无数据")
        self.benchmark_prices = {}
        self.benchmark_available = False

    def run(self) -> BacktestResult:
        """运行回测"""
        print("=" * 60)
        print("  回测引擎启动")
        print("=" * 60)
        print(f"  初始资金: {self.initial_capital:,.0f}")
        print(f"  期间: {self.start_date} ~ {self.end_date}")
        print(f"  最少买入: {self.min_buy:,.0f}")
        print(f"  最大持仓: {self.max_positions}")
        print(f"  佣金: {self.commission*100:.3f}%  印花税: {self.stamp_tax*100:.3f}%")
        print(f"  滑点: {self.slippage*100:.3f}%")
        print(f"  再平衡: {self.rebalance_days}天")

        # 加载策略
        self._load_strategies()

        # 加载数据
        self._load_data()

        # 重置状态
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.daily_assets = []

        last_total = self.initial_capital
        last_benchmark = self.initial_capital

        # 基准初始值
        first_bm = None
        if self.benchmark_prices:
            first_bm = list(self.benchmark_prices.values())[0]

        total_days = len(self.trading_dates)

        for i, date_str in enumerate(self.trading_dates):
            day_num = i + 1
            is_rebalance = (self.rebalance_days <= 0 or
                            day_num == 1 or
                            day_num % self.rebalance_days == 0)

            if day_num % max(1, total_days // 20) == 0 or day_num == 1:
                print(f"  进度: {day_num}/{total_days} | {date_str} | "
                      f"持仓:{len(self.positions)} 现金:{self.cash:,.0f}")

            # 选股
            if is_rebalance or day_num == 1:
                buy_result = self.buy_strategy.select(
                    date_str, kline_data=self.kline_data)
            else:
                buy_result = BuyResult(stocks=list(self.positions.keys()))

            selected = buy_result.stocks

            # 获取今日价格（含持仓股，供卖出策略使用）
            price_stocks = list(set(selected + list(self.positions.keys())))
            today_prices = self._get_today_prices(date_str, price_stocks)

            # 卖出
            sell_signals = self.sell_strategy.decide(
                self._positions_to_dict(), date_str,
                selected, today_prices, is_rebalance)

            for sig in sell_signals:
                self._execute_sell(sig, date_str)

            # 买入
            if self.cash >= self.min_buy and selected:
                self._execute_buy(selected, today_prices, date_str,
                                  day_num == 1)

            # 更新持仓最高价
            for stock, pos in self.positions.items():
                if stock in today_prices and today_prices[stock] > 0:
                    if today_prices[stock] > pos.peak_price:
                        pos.peak_price = today_prices[stock]

            # 计算当日资产
            stock_value = self._calc_stock_value(today_prices)
            total_value = self.cash + stock_value

            # 基准值
            bm_value = self._calc_benchmark(date_str, first_bm, last_benchmark)
            last_benchmark = bm_value or last_benchmark

            # 节假日无数据，维持上日值
            if not today_prices:
                total_value = last_total
            last_total = total_value

            self.daily_assets.append(DailyAsset(
                date=date_str,
                cash=self.cash,
                stock_value=stock_value,
                total_value=total_value,
                positions=len(self.positions),
                benchmark_value=bm_value or last_benchmark,
            ))

        # 回测结束
        final_value = (self.daily_assets[-1].total_value
                       if self.daily_assets else self.initial_capital)

        # 平仓
        self._close_positions(self.trading_dates[-1])

        print(f"\n{'='*60}")
        print(f"  回测完成")
        print(f"{'='*60}")
        print(f"  初始: {self.initial_capital:,.0f} → 最终: {final_value:,.0f}")
        print(f"  收益: {(final_value/self.initial_capital-1)*100:.2f}%")
        print(f"  交易: {len([t for t in self.trades if t.action=='BUY'])}买 "
              f"{len([t for t in self.trades if t.action=='SELL'])}卖")

        return BacktestResult(
            trades=self.trades,
            daily_assets=self.daily_assets,
            config=self.config,
            initial_capital=self.initial_capital,
            final_value=final_value,
            benchmark_available=self.benchmark_available,
        )

    # ── 内部方法 ─────────────────────────────────────

    def _get_today_prices(self, date_str: str, stocks: list) -> dict:
        """获取指定日期的收盘价"""
        prices = {}
        target = pd.Timestamp(date_str)
        try:
            date_data = self.kline_data.xs(target, level='date',
                                           drop_level=False)
            for s in stocks:
                try:
                    p = date_data.loc[(target, s), 'close']
                    if pd.notna(p) and p > 0:
                        prices[s] = float(p)
                except (KeyError, TypeError):
                    continue
        except KeyError:
            pass
        return prices

    def _positions_to_dict(self) -> dict:
        """转换持仓格式供卖出策略使用"""
        return {
            s: {'shares': p.shares, 'cost': p.cost,
                'buy_date': p.buy_date, 'peak_price': p.peak_price}
            for s, p in self.positions.items()
        }

    def _execute_sell(self, sig: SellSignal, date_str: str):
        """执行卖出"""
        pos = self.positions.get(sig.stock)
        if pos is None:
            return
        if sig.shares <= 0 or sig.price <= 0:
            return

        actual_shares = min(sig.shares, pos.shares)
        if actual_shares <= 0:
            return

        # 滑点模拟：实际卖出价 = 信号价 × (1 - 滑点)
        actual_price = sig.price * (1 - self.slippage)
        revenue = actual_price * actual_shares
        # 佣金 + 印花税
        fee = revenue * (self.commission + self.stamp_tax)
        cash_in = revenue - fee

        profit = (actual_price - pos.cost) * actual_shares

        cash_before = self.cash
        self.cash += cash_in
        pos.shares -= actual_shares

        self.trades.append(TradeRecord(
            date=date_str, stock=sig.stock, action='SELL',
            price=actual_price, shares=actual_shares,
            cost=cash_in, profit=profit, reason=sig.reason,
            cash_before=cash_before, cash_after=self.cash,
            pnl_pct=(actual_price/pos.cost - 1)*100
        ))

        if pos.shares <= 0:
            del self.positions[sig.stock]

    def _execute_buy(self, selected: list, prices: dict,
                     date_str: str, is_first_day: bool):
        """执行买入（等权重分仓）"""
        has_position = set(p.stock for p in self.trades
                           if p.action == 'BUY' and p.date == date_str)

        # 过滤已有持仓和当日已买的
        to_buy = [s for s in selected
                  if s not in self.positions
                  and s in prices
                  and prices[s] > 0]

        if not to_buy:
            return

        # 限制最大持仓数
        slots_left = self.max_positions - len(self.positions)
        if slots_left <= 0:
            return
        to_buy = to_buy[:slots_left]

        # 等权重分仓
        per_stock = self.cash / len(to_buy)

        for stock in to_buy:
            price = prices[stock]
            if price <= 0:
                continue

            # 滑点：实际买入价 = 信号价 × (1 + 滑点)
            actual_price = price * (1 + self.slippage)
            shares = int(per_stock / actual_price / 100) * 100
            if shares <= 0:
                continue

            cost = actual_price * shares
            fee = cost * self.commission
            total_cost = cost + fee

            if total_cost > self.cash:
                continue

            reason = '初始买入' if is_first_day else '调仓买入'

            cash_before = self.cash
            self.cash -= total_cost

            self.positions[stock] = Position(
                shares=shares, cost=actual_price,
                buy_date=date_str, peak_price=actual_price
            )

            self.trades.append(TradeRecord(
                date=date_str, stock=stock, action='BUY',
                price=actual_price, shares=shares,
                cost=cost, profit=-fee, reason=reason,
                cash_before=cash_before, cash_after=self.cash
            ))

    def _calc_stock_value(self, today_prices: dict) -> float:
        """计算持仓市值"""
        total = 0.0
        for stock, pos in self.positions.items():
            if stock in today_prices and today_prices[stock] > 0:
                total += today_prices[stock] * pos.shares
            else:
                total += pos.cost * pos.shares
        return total

    def _calc_benchmark(self, date_str: str,
                        first_price: float,
                        last_value: float) -> Optional[float]:
        """计算基准当日价值"""
        if date_str in self.benchmark_prices:
            bp = self.benchmark_prices[date_str]
            if bp and first_price and first_price > 0:
                return bp / first_price * self.initial_capital
        return last_value

    def _close_positions(self, final_date: str):
        """回测结束时平仓"""
        for stock, pos in list(self.positions.items()):
            self.trades.append(TradeRecord(
                date=final_date, stock=stock, action='SELL',
                price=pos.cost, shares=pos.shares,
                cost=pos.cost * pos.shares, profit=0,
                reason='结束平仓'
            ))
        self.positions.clear()
