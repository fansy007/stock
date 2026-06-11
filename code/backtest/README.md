# 回测系统

## 目录结构

```
code/backtest/
├── config/                     # JSON 配置文件
│   ├── backtest.json           # 回测主配置（资金、期间、策略选择）
│   ├── buy_factor.json         # 买入策略配置（因子、股票池、选股参数）
│   ├── sell.json               # 卖出策略配置（模式、止损止盈参数）
│   └── alpha101_factors.json   # 101 个 Alpha 因子说明文档
├── data/
│   └── loader.py               # K线数据加载（从 export/data/kline/ 读取 CSV）
├── strategy/
│   ├── protocol.py             # 买卖策略接口定义
│   ├── buy_factor_strategy.py  # Alpha101 因子选股策略
│   └── sell_trailing_strategy.py # 多模式卖出策略
├── engine.py                   # 回测引擎主循环
├── metrics.py                  # 绩效指标计算+报告输出
├── main.py                     # CLI 入口
└── output/                     # 回测结果输出目录
```

## 快速开始

```bash
# 从项目根目录（stock/）运行
cd /Users/hg26502/claude/stock

# 使用默认配置跑回测
python3 -m code.backtest.main

# 指定配置文件
python3 -m code.backtest.main --config my_config.json

# 保存结果并生成图表
python3 -m code.backtest.main --save --plot
```

**前提：** `export/data/kline/` 目录下需要有股票日线 CSV 文件（列：time, open, high, low, close, volume, amount），以及 `export/data/stock_list.csv`。

## 配置文件详解

### 1. 回测主配置 `backtest.json`

```json
{
    "capital": {
        "initial": 1000000,          // 初始资金
        "min_buy": 50000,            // 单笔最低买入金额
        "commission_rate": 0.0003,   // 佣金费率（万三）
        "stamp_tax_rate": 0.001,     // 印花税率（千一）
        "slippage": 0.001            // 滑点（千一）
    },
    "period": {
        "start": "20260401",         // 回测开始日期 YYYYMMDD
        "end": "20260507"            // 回测结束日期 YYYYMMDD
    },
    "portfolio": {
        "max_positions": 20,         // 最大持仓数
        "position_sizing": "equal_weight"  // 仓位分配方式（当前仅支持等权重）
    },
    "benchmark": "399006.SZ",        // 基准指数代码
    "strategies": {
        "buy": "buy_factor_strategy",   // 买入策略模块名（取 buy_{name}_strategy）
        "sell": "sell_trailing_strategy" // 卖出策略模块名
    },
    "rebalance_days": 5              // 调仓间隔（交易日数，0=不调仓）
}
```

### 2. 因子买入配置 `buy_factor.json`

```json
{
    "factors": ["alpha002", "alpha006", "alpha012"],  // 使用的 Alpha 因子列表
    "factor_reverse": false,        // true=因子值越小越好（如波动率因子）
    "factor_weights": {             // 因子加权（空对象=等权重）
        "alpha002": 1.0,
        "alpha006": 1.2
    },
    "normalization": "zscore",      // 归一化方法：zscore / rank / minmax
    "stock_pool": {
        "source": "industry",       // 股票池来源：industry / list / csv
        "industry": "创业板",        // 板块（创业板/科创板/主板/沪深300等）
        "exclude_st": true,         // 是否排除 ST 股票
        "exclude_new_stocks_days": 60, // 上市不足 N 天剔除
        "min_price": 3.0            // 最低股价过滤
    },
    "selection": {
        "top_n": 10,                // 选股数量
        "min_score": 0              // 最低得分门槛
    }
}
```

**股票池 source 说明：**

| source   | 说明 |
|----------|------|
| industry | 按板块代码前缀过滤（创业板=300/301，科创板=688，主板=600/601/603/605/000/001/002） |
| list     | 从配置的 `list` 字段取固定列表 |
| csv      | 从 CSV 文件读取股票列表 |

**归一化方法对比：**

| 方法   | 特点 |
|--------|------|
| zscore | (x-mean)/std×50+50，±3σ截尾。保留量级信息，推荐默认 |
| rank   | 百分位排名 0-100，最稳健，丢失量级信息 |
| minmax | (x-min)/(max-min)×100，易被极端值拉偏 |

### 3. 卖出配置 `sell.json`

```json
{
    "mode": "stop_take",            // 模式：stop_take / trailing / time_only / hybrid
    "hold_days_min": 1,             // 最小持有天数（保护，N天内不触发卖出）
    "hold_days_max": 60,            // 最大持有天数（强制卖出）
    "stop_loss_pct": 8.0,           // 止损：从最高点回撤 8%
    "take_profit_pct": 20.0,        // 止盈：盈利 20%
    "take_profit_mode": "all",      // all（全仓）或 partial（分批）
    "partial_take_profit_levels": [
        {"pct": 15, "sell_ratio": 0.3},
        {"pct": 30, "sell_ratio": 0.3},
        {"pct": 50, "sell_ratio": 0.4}
    ],
    "trailing_stop_pct": 5.0,       // 移动止损回撤幅度
    "trailing_activate_pct": 10.0,  // 盈利超过此值后启动移动止损
    "rebalance_sell": true          // 调仓日是否卖出不在新选股中的持仓
}
```

**模式说明：**

| 模式 | 用途 |
|------|------|
| stop_take | 传统止损止盈。从最高点回撤8%止损，盈利20%止盈 |
| trailing | 移动止损。盈利超过10%后启动，从随后最高点回撤5%卖出 |
| time_only | 纯时间卖出。持有 N 天后强制卖出，适合因子效果测试 |
| hybrid | 组合模式：同时检查止损+止盈+移动止损+调仓卖出 |

## 运行流程

```
加载配置 → 加载策略 → 加载K线数据(含180天缓冲) → 每日循环:
  ├─ 调仓日: 因子选股（计算 Alpha101 → 归一化 → 综合打分 → TOP N）
  ├─ 非调仓日: 维持当前持仓
  ├─ 卖出: 止损/止盈/调仓/移动止损 检查
  ├─ 买入: 等权重分仓，限制最大持仓数
  └─ 记录每日资产快照
→ 计算绩效指标 → 输出报告
```

引擎启动时自动多加载 180 天历史数据用于因子计算预热，回测期间不再从文件系统读取数据。

## 编写自定义策略

### 买入策略

在 `code/backtest/strategy/` 下创建 `buy_{name}_strategy.py`，实现 `BuyStrategy` 类：

```python
from code.backtest.strategy.protocol import BaseBuyStrategy, BuyResult

class BuyStrategy(BaseBuyStrategy):
    def load_config(self) -> dict:
        return {}   # 返回配置字典

    def select(self, date: str, kline_data=None, stock_list=None) -> BuyResult:
        # date: YYYYMMDD
        # kline_data: MultiIndex (date, symbol) DataFrame
        # 返回选中的股票列表
        return BuyResult(stocks=['300750.SZ', '300059.SZ'], date=date)
```

然后改 `backtest.json` 的 `strategies.buy` 为你的模块名 `{name}`。

### 卖出策略

创建 `sell_{name}_strategy.py`，实现 `SellStrategy` 类：

```python
from code.backtest.strategy.protocol import BaseSellStrategy, SellSignal

class SellStrategy(BaseSellStrategy):
    def load_config(self) -> dict:
        return {}

    def decide(self, positions, date, new_buy_list, prices, is_rebalance) -> list:
        # positions: {stock: {shares, cost, buy_date, peak_price}}
        # date: YYYYMMDD
        # prices: {stock: price}
        # 返回 SellSignal 列表
        signals = []
        for stock, pos in positions.items():
            if stock in prices:
                signals.append(SellSignal(
                    stock=stock, reason='我的卖出逻辑',
                    price=prices[stock], shares=pos['shares']
                ))
        return signals
```

### 命名规则

- 文件名必须包含 `strategy`
- 买入策略：`buy_{name}_strategy.py` → `backtest.json` 中填 `buy_{name}_strategy`
- 卖出策略：`sell_{name}_strategy.py` → 填 `sell_{name}_strategy`
- 类名必须叫 `BuyStrategy` 或 `SellStrategy`

## 输出说明

运行后输出到 `code/backtest/output/`：

- `backtest_trades.csv` — 逐笔交易记录
- `backtest_assets.csv` — 每日资产快照
- `backtest_curve.png` — 资产曲线图（需 matplotlib）

### 绩效指标

| 指标 | 说明 |
|------|------|
| 年化收益率 | 按 252 个交易日年化 |
| 年化波动率 | 日收益率标准差 × √252 |
| 最大回撤 | 从峰值到谷底的最大跌幅 |
| 夏普比率 | (年化收益 - 无风险利率) / 年化波动 |
| 胜率 | 盈利交易次数 / 总交易次数 |
| 盈亏比 | 平均盈利 / 平均亏损 |
