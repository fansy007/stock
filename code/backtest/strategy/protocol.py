"""
买卖策略协议（接口定义）

所有策略模块必须实现：
- BuyStrategy: 选股逻辑
- SellStrategy: 卖出决策逻辑

策略文件命名规则：{buy|sell}_{name}_strategy.py
模块必须暴露符合协议的函数。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SellSignal:
    """卖出信号"""
    stock: str
    reason: str          # 卖出原因描述
    price: float         # 卖出价格
    shares: int          # 卖出数量
    profit: float = 0    # 盈亏金额
    pnl_pct: float = 0   # 盈亏百分比


@dataclass
class BuyResult:
    """买入策略输出"""
    stocks: list = field(default_factory=list)
    prices: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    date: str = ''


class BaseBuyStrategy(ABC):
    """买入策略基类"""

    @abstractmethod
    def select(self, date: str) -> BuyResult:
        """给定日期，返回要买入的股票及价格"""
        ...

    @abstractmethod
    def load_config(self) -> dict:
        """加载策略配置"""
        ...


class BaseSellStrategy(ABC):
    """卖出策略基类"""

    @abstractmethod
    def decide(self, positions: dict, date: str,
               new_buy_list: list, prices: dict,
               is_rebalance: bool = False) -> list:
        """决定哪些持仓要卖出，返回 SellSignal 列表"""
        ...

    @abstractmethod
    def load_config(self) -> dict:
        """加载策略配置"""
        ...


def load_buy_strategy(module_name: str) -> BaseBuyStrategy:
    """动态加载买入策略模块，返回策略实例

    Args:
        module_name: 策略模块名，如 'buy_factor_strategy'
                     将在 strategy/ 目录下查找 {module_name}.py
    """
    import importlib
    import sys
    import os

    # 使用完整的包路径导入
    full_name = f"code.backtest.strategy.{module_name}"
    module = importlib.import_module(full_name)

    if hasattr(module, 'BuyStrategy'):
        strategy_cls = module.BuyStrategy
        instance = strategy_cls()
        return instance

    raise ImportError(f"策略模块 {module_name} 未找到 BuyStrategy 类")


def load_sell_strategy(module_name: str) -> BaseSellStrategy:
    """动态加载卖出策略模块"""
    import importlib
    import sys
    import os

    full_name = f"code.backtest.strategy.{module_name}"
    module = importlib.import_module(full_name)

    if hasattr(module, 'SellStrategy'):
        strategy_cls = module.SellStrategy
        instance = strategy_cls()
        return instance

    raise ImportError(f"策略模块 {module_name} 未找到 SellStrategy 类")
