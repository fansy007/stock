"""
多模式卖出策略

支持模式：
- time_only: 持有 N 天后强制卖出（因子测试用）
- stop_take: 传统止损止盈（增强版）
- trailing: 移动止损
- hybrid: 组合模式

文件命名含 strategy 以符合策略发现规则。
"""
import os
import json
from datetime import datetime, timedelta

from code.backtest.strategy.protocol import BaseSellStrategy, SellSignal

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'sell.json')


def load_config(config_path: str = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    defaults = {
        "mode": "stop_take",
        "hold_days_min": 1,
        "hold_days_max": 0,
        "stop_loss_pct": 8.0,
        "take_profit_pct": 20.0,
        "take_profit_mode": "all",
        "partial_take_profit_levels": [
            {"pct": 15, "sell_ratio": 0.3},
            {"pct": 30, "sell_ratio": 0.3},
            {"pct": 50, "sell_ratio": 0.4}
        ],
        "trailing_stop_pct": 5.0,
        "trailing_activate_pct": 10.0,
        "rebalance_sell": True
    }
    if not os.path.exists(path):
        return defaults
    with open(path, 'r', encoding='utf-8') as f:
        loaded = json.load(f)
        defaults.update(loaded)
        return defaults


def _parse_date(date_str: str):
    return datetime.strptime(date_str, '%Y%m%d')


class SellStrategy(BaseSellStrategy):
    """多模式卖出策略"""

    def __init__(self, config_path: str = None):
        self._config = None
        self._config_path = config_path
        # 记录已部分止盈的股票和层级
        self._partial_sold = {}  # {stock: [已卖出比例, 已触发层级]}

    def load_config(self) -> dict:
        if self._config is None:
            self._config = load_config(self._config_path)
        return self._config

    def decide(self, positions: dict, date: str,
               new_buy_list: list, prices: dict,
               is_rebalance: bool = False) -> list:
        """决定卖出"""
        config = self.load_config()
        mode = config.get('mode', 'stop_take')
        signals = []

        for stock, pos in list(positions.items()):
            if stock not in prices:
                continue

            price = prices[stock]
            if price is None or price != price:
                continue

            cost = pos['cost']
            shares = pos['shares']
            peak = pos.get('peak_price', cost)
            buy_date = pos.get('buy_date', date)

            # 更新最高价
            if price > peak:
                peak = price
                pos['peak_price'] = peak

            profit_amt = (price - cost) * shares
            profit_pct = (price - cost) / cost * 100

            # 模式 1: 纯时间卖出（因子测试用）
            if mode == 'time_only':
                sig = self._check_time_only(stock, date, buy_date, price, shares,
                                            profit_amt, profit_pct, config)
                if sig:
                    signals.append(sig)
                continue

            # 最小持有天数保护
            if config.get('hold_days_min', 0) > 0:
                hold_days = (_parse_date(date) - _parse_date(buy_date)).days
                if hold_days < config['hold_days_min']:
                    continue

            # 最大持有天数强制卖出
            if config.get('hold_days_max', 0) > 0:
                sig = self._check_time_only(stock, date, buy_date, price, shares,
                                            profit_amt, profit_pct, config,
                                            key='hold_days_max')
                if sig:
                    signals.append(sig)
                    continue

            # 止损检查
            if mode in ('stop_take', 'hybrid'):
                sig = self._check_stop_loss(stock, peak, price, shares,
                                            profit_amt, config)
                if sig:
                    signals.append(sig)
                    continue

            # 止盈检查
            if mode in ('stop_take', 'hybrid'):
                sig = self._check_take_profit(stock, price, cost, shares,
                                              profit_amt, profit_pct, config)
                if sig:
                    signals.append(sig)
                    continue

            # 移动止损
            if mode == 'trailing':
                sig = self._check_trailing_stop(stock, peak, price, shares,
                                                profit_amt, profit_pct, config)
                if sig:
                    signals.append(sig)
                    continue

            # 调仓卖出
            if is_rebalance and config.get('rebalance_sell', True):
                if new_buy_list and stock not in new_buy_list:
                    signals.append(SellSignal(
                        stock=stock, reason='调仓卖出',
                        price=price, shares=shares,
                        profit=profit_amt, pnl_pct=profit_pct
                    ))
                    continue

        return signals

    def _check_time_only(self, stock, date, buy_date, price, shares,
                         profit_amt, profit_pct, config, key='hold_days_max'):
        """纯时间卖出检查"""
        max_days = config.get(key, 0)
        if max_days <= 0:
            return None
        hold_days = (_parse_date(date) - _parse_date(buy_date)).days
        if hold_days >= max_days:
            return SellSignal(
                stock=stock, reason=f'{key}={max_days}天到',
                price=price, shares=shares,
                profit=profit_amt, pnl_pct=profit_pct
            )
        return None

    def _check_stop_loss(self, stock, peak, price, shares, profit_amt, config):
        """止损检查：从最高点回撤"""
        pct = config.get('stop_loss_pct', 0)
        if pct <= 0:
            return None
        if peak <= 0:
            return None
        drawdown = (peak - price) / peak * 100
        if drawdown >= pct:
            return SellSignal(
                stock=stock, reason=f'止损({drawdown:.1f}%>={pct}%)',
                price=price, shares=shares, profit=profit_amt
            )
        return None

    def _check_take_profit(self, stock, price, cost, shares,
                           profit_amt, profit_pct, config):
        """止盈检查：支持分批止盈"""
        mode = config.get('take_profit_mode', 'all')

        if mode == 'all':
            pct = config.get('take_profit_pct', 0)
            if pct > 0 and profit_pct >= pct:
                return SellSignal(
                    stock=stock, reason=f'止盈({profit_pct:.1f}%>={pct}%)',
                    price=price, shares=shares, profit=profit_amt, pnl_pct=profit_pct
                )

        elif mode == 'partial':
            levels = config.get('partial_take_profit_levels', [])
            sold_ratio, triggered = self._partial_sold.get(stock, (0.0, -1))

            for i, level in enumerate(levels):
                if i <= triggered:
                    continue
                target_pct = level['pct']
                sell_ratio = level['sell_ratio']

                if profit_pct >= target_pct:
                    sell_shares = max(1, int(shares * sell_ratio))
                    new_triggered = i
                    self._partial_sold[stock] = (sold_ratio + sell_ratio, new_triggered)
                    return SellSignal(
                        stock=stock,
                        reason=f'分批止盈{target_pct}%(卖{sell_ratio*100:.0f}%)',
                        price=price, shares=sell_shares,
                        profit=profit_amt * sell_ratio, pnl_pct=profit_pct
                    )

        return None

    def _check_trailing_stop(self, stock, peak, price, shares,
                             profit_amt, profit_pct, config):
        """移动止损：盈利超过激活线后启动"""
        activate = config.get('trailing_activate_pct', 0)
        trail_pct = config.get('trailing_stop_pct', 0)
        if trail_pct <= 0:
            return None

        # 还没盈利到激活线，不触发
        if profit_pct < activate:
            return None

        # 从最高点回撤超过 trail_pct
        if peak > 0:
            drawdown = (peak - price) / peak * 100
            if drawdown >= trail_pct:
                return SellSignal(
                    stock=stock,
                    reason=f'移动止损(峰{peak:.2f}→{price:.2f},回撤{drawdown:.1f}%)',
                    price=price, shares=shares, profit=profit_amt, pnl_pct=profit_pct
                )
        return None
