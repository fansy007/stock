# stock-portfolio Skill 设计方案

## 背景

海宁需要记录每日证券账户的**总资产、持仓明细、成交记录**，存入 MongoDB，支持 CLI 和 Web 界面增删改查。数据来源于国金证券 App 截图的手工录入。

一人专用，无需多账户相关字段。

## 数据模型

**集合名:** `vocab.portfolio_logs`

**文档结构**（一条 = 一天的完整快照）：

```python
{
    "_id": ObjectId,
    "date": "2026-07-03",                        # 日期 YYYY-MM-DD（唯一，一天一条）

    # 账户总览
    "total_assets": 1077215.90,                   # 总资产
    "market_value": 1076678.58,                    # 总市值
    "total_pnl": 24748.78,                        # 总盈亏
    "daily_pnl": 15393.95,                         # 当日盈亏
    "cash_balance": 1.92,                          # 资金余额
    "withdrawable": 1.92,                          # 可取金额
    "available": 1.92,                             # 可用金额

    # 持仓列表（嵌入数组）
    "holdings": [
        {
            "code": "603259", "name": "药明康德",
            "price": 124.120, "pnl": -20.320,
            "daily_pnl": 1128.000, "pnl_pct": -0.041,
            "shares": 400, "balance": 400.000, "available": 400.000
        },
        ...
    ],

    # 当日成交（嵌入数组）
    "trades": [
        {
            "time": "14:58:00", "code": "131810", "name": "R-001",
            "action": "卖出", "shares": 5200, "price": 0.915,
            "amount": 520000.000, "contract_id": "76816",
            "trade_id": "06010000004499196"
        },
        ...
    ],

    "created_at": datetime.utcnow,
    "updated_at": datetime.utcnow
}
```

**唯一约束:** `date` 字段唯一（同一天只能有一条记录）。

## 文件清单

### 新建文件

| 文件 | 用途 |
|------|------|
| `stock/core/code/portfolio/__init__.py` | 空，包标记 |
| `stock/core/code/portfolio/db.py` | MongoDB CRUD |
| `stock/core/code/portfolio/cli.py` | 命令行接口 |
| `stock/core/code/portfolio/web.py` | Streamlit UI |
| `~/.claude/skills/stock-portfolio/SKILL.md` | Skill 文档 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `stock/app.py` | 新增一个 tab 引入 `render_portfolio()` |
| `CLAUDE.md` | 注册 stock-portfolio skill |

## 各文件详细设计

### 1. db.py

完全复用 `candidates/db.py` 的 MongoDB 连接模式（单例 `_get_client()` + `get_db()`）。

**函数签名：**

```python
def ensure_indexes()
    # date 唯一索引
    # date 单字段索引（倒序）

def create_log(date, total_assets=None, market_value=None, total_pnl=None,
               daily_pnl=None, cash_balance=None, withdrawable=None,
               available=None, holdings=None, trades=None) -> str
    """新建一条日终日志。date 已存在则更新（upsert on date）。"""

def get_log(id: str) -> dict | None
    """按 _id 查询单条"""

def get_log_by_date(date: str) -> dict | None
    """按日期查询单条"""

def list_logs(date_from: str = None, date_to: str = None,
              sort: str = "-date", limit: int = 100) -> list[dict]

def update_log(id: str, updates: dict) -> bool
    """字段白名单 + $set"""
    allowed = {"total_assets", "market_value", ..., "holdings", "trades"}

def delete_log(id: str) -> bool

def latest_log() -> dict | None
    """返回最近一条日志"""
```

### 2. cli.py

复用 `predictions/cli.py` 的 argparse 模式 + `_to_json()`/`_print_table()` 辅助函数。

**子命令：**

```bash
# 添加（用 --holdings-json 传持仓数组，--trades-json 传成交数组）
python3 -m core.code.portfolio.cli add \
  --date 2026-07-03 \
  --total-assets 1077215.90 \
  --market-value 1076678.58 \
  --total-pnl 24748.78 \
  --daily-pnl 15393.95 \
  --cash-balance 1.92

# 或从文件读持仓/成交
python3 -m core.code.portfolio.cli add \
  --date 2026-07-03 \
  --total-assets 1077215.90 \
  --daily-pnl 15393.95 \
  --holdings-file holdings.json \
  --trades-file trades.json

# 列表
python3 -m core.code.portfolio.cli list
python3 -m core.code.portfolio.cli list --from 2026-07-01 --to 2026-07-03

# 查看单条
python3 -m core.code.portfolio.cli get <id>
python3 -m core.code.portfolio.cli get-by-date 2026-07-03

# 更新
python3 -m core.code.portfolio.cli update <id> --total-assets 1080000.00 --daily-pnl 16000.00

# 删除
python3 -m core.code.portfolio.cli delete <id>
```

### 3. web.py

Streamlit UI，单入口 `render_portfolio()`，在 app.py 中引用。

**子页（st.tabs）：**

| Tab | 内容 |
|-----|------|
| 📊 总览 | 最新快照卡片（总资产/市值/盈亏）+ 总资产趋势图 |
| 📋 持仓 | 最新持仓列表，可回溯历史某天的持仓 |
| 📝 成交 | 成交记录列表，按日期筛选 |
| ➕ 录入 | 表单录入新的日终快照（含持仓和成交表格） |

**关键交互：**
- 总览页：显示最近 N 天总资产折线图（用 `st.line_chart`）
- 录入页：大表单，三个区块（账户总览字段 + 持仓表格 + 成交表格）
- 持仓/成交表格支持 st.data_editor 直接编辑

### 4. app.py 改动

```python
# 导入
from core.code.portfolio.web import render_portfolio

# 在 tabs 定义中追加一行
_tabs = st.tabs([
    "⭐ 自选股",
    "🔮 预判复盘",
    "📊 概念板块",
    "📋 选股列表",
    "📊 详情",
    "📈 走势",
    "📡 跟踪雷达",
    "📊 投资组合",    # 新 tab
])

# 渲染
with _tabs[7]:
    render_portfolio()
```

### 5. SKILL.md

标准 skill 文档结构：YAML frontmatter → 数据架构（字段表）→ CLI 速查 → Web 界面说明 → 对话框行为（识别到海宁查看/更新持仓数据时主动询问）。

### 6. CLAUDE.md

追加一行：`- **stock-portfolio** — 每日持仓/成交/总资产记录，CLI+Web 增删改查`

## 实现顺序

1. `__init__.py` + `db.py`（CRUD + 索引）
2. `cli.py`（argparse 子命令）
3. `web.py`（Streamlit UI）
4. `app.py` 改动（追加 tab）
5. `SKILL.md` + `CLAUDE.md` 注册

## 验证方式

1. CLI 测试：`python3 -m core.code.portfolio.cli add ...` → `list` → `get` → `update` → `delete`
2. Web 测试：启动 `./run_web.sh` → 切换到「📊 投资组合」tab → 录入数据 → 查看总览
3. MongoDB 验证：`mongosh vocab --eval "db.portfolio_logs.find().pretty()"`
