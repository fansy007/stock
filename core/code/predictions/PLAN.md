# 预判系统实现方案

## 目录结构

```
stock/core/code/predictions/
  __init__.py          # 空
  db.py                # MongoDB CRUD 封装
  cli.py               # 命令行入口（skill + webapp 调用）
  web.py               # Streamlit 渲染
  PLAN.md              # 本文档
```

## MongoDB

复用 vocab 同一实例 `localhost:27017`，数据库用已有的 **`vocab`**，不建新库。两个新集合。

### 集合：predictions

```javascript
{
  _id: ObjectId,
  created_at: ISODate,
  updated_at: ISODate,

  originator: "海宁",         // 海宁/爱因斯坦/共同
  target: "菲利华",           // 标的
  judgment: "Q布落地前不因价格波动做方向性决策",
  rationale: "基本面未变...",   // 选填，自由文本
  confidence: "中",            // 低/中偏低/中/中偏高/高/信念

  deadline: ISODate,           // 选填，null=框架级
  result: "pending",           // pending/correct/wrong/expired
  review: "",                  // 选填，验证复盘

  lesson_type_id: ObjectId,    // 选填，指向 lesson_types
  lesson: "",                  // 选填

  tags: ["A股"],               // 选填

  supersedes: null,            // 替代了哪个预判的 _id
  superseded_by: null,         // 被哪个预判替代
}
```

**不在 schema 里的东西（已砍掉）：**
- 没有 `direction`、`category`、`code`
- 没有 `decisions` 嵌入
- 没有 `reminders` 集合

### 集合：lesson_types

```javascript
{
  _id: ObjectId,
  name: "纪律执行",
  description: "违反了自己定的规则"
}
```

初始种子：

| name | description |
|------|-------------|
| 纪律执行 | 违反了自己定的规则 |
| 分析框架 | 框架/推理方式有问题 |
| 认知偏差 | 理性市场假设、确认偏差等心理效应 |
| 执行流程 | 流程没走完就动手（快一小步） |
| 仓位管理 | 仓位/资金规划问题 |
| 判断方法 | 技术性的判断方法缺陷 |

### 索引

```javascript
predictions:  {result: 1, deadline: 1}
predictions:  {target: 1, created_at: -1}
predictions:  {created_at: -1}
lesson_types: {name: 1}   // unique
```

## Python 模块

### db.py — CRUD 封装

```python
def get_db() -> pymongo.database.Database
# localhost:27017，vocab 库，返回 db 对象

# predictions
def create_prediction(data: dict) -> str
def get_prediction(id: str) -> dict | None
def list_predictions(result=None, target=None, originator=None,
                     sort="-created_at", limit=100) -> list[dict]
def update_prediction(id: str, updates: dict) -> bool
def delete_prediction(id: str) -> bool
def supersede_prediction(old_id: str, new_id: str)

# lesson_types
def list_lesson_types() -> list[dict]
def add_lesson_type(name: str, desc: str = "") -> str

# seed
def seed_lesson_types()
```

### cli.py — 命令行入口

skill 和 webapp 都通过 cli.py 操作数据。

```
# 新建
python cli.py add --target 菲利华 --judgment "Q布..." --confidence 中

# 列出，默认 result=pending
python cli.py list
python cli.py list --result correct
python cli.py list --target 菲利华

# 查看单条
python cli.py get <id>

# 更新（通用）
python cli.py update <id> --result correct --review "验证通过"

# 删除
python cli.py delete <id>

# lesson_type 管理
python cli.py lesson-types
python cli.py add-lesson-type --name "xxx" --desc "xxx"

# 迁移预判经验画像（从 md 导入 lesson + bias）
python cli.py import-experience --file "预判经验画像.md"
```

### web.py — Streamlit 渲染

`render_predictions()` 函数，和 `code/backtest/web.py` → `render_backtest_page()` 同一模式。

**Webapp 功能范围：view + update，不建不删。**

三个子 tab：

**Tab 1: 待验证**
- `result=pending`，按 `deadline` 升序，已过期的红色标记
- 每行：target + judgment 摘要 + confidence + deadline
- 点击展开 → 填验证结果 (correct/wrong/expired) + review + lesson
- 提交 → 调 CLI update

**Tab 2: 已归档**
- `result=correct/wrong/expired`，按 `created_at` 降序
- 展开查看 review + lesson

**Tab 3: 新建预判**
- 表单：target / judgment / confidence / rationale / deadline / originator
- 提交 → 调 CLI add
- 提交前自动查历史同 target 的 wrong 预判，弹出教训提示

### app.py 改动

```python
from core.code.predictions.web import render_predictions

_tabs = st.tabs(["📊 概念板块", "📋 选股列表", "📊 详情", "📈 走势", "📡 跟踪雷达", "🔮 预判复盘"])

with _tabs[5]:
    render_predictions()
```

## Skill 接口

新增 skill `stock_prediction`。

skill 通过 CLI 执行操作：对话中产生预判 → 爱因斯坦调 `cli.py add` 写入；到期提醒 → 爱因斯坦主动问 "要不要更新状态" → 调 `cli.py update`。

## 不做的事（确认清单）

| 事项 | 状态 |
|------|------|
| 关旧建新（supersedes） | ✅ 保留 |
| direction/category 双轴 | ❌ 砍掉 |
| code 字段 | ❌ 砍掉 |
| decisions 嵌入 | ❌ 砍掉 |
| reminders 集合 | ❌ 砍掉 |
| cron 自动提醒 | ❌ 砍掉，由 skill 手动触发 |
| Obsidian 集成 | ❌ 砍掉 |
| stock-analysis 交叉查询 | ❌ 砍掉 |
| 跟踪雷达关联 | ❌ 砍掉 |
| prediction_experience 独立集合 | ❌ 砍掉，md 导入到 lesson_types |

## 实现顺序

1. `db.py` — MongoDB CRUD + seed_lesson_types
2. `cli.py` — 命令行入口，所有操作可 CLI 完成
3. `web.py` — Streamlit 渲染
4. `app.py` — 加 tab
5. 数据迁移（md → MongoDB）
6. stock_prediction skill 注册
