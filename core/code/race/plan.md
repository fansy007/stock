# stock-race 赛马系统设计方案

## 核心理念

不给 agent 分配投资流派（价值/趋势/事件/赔率），只给性格。工具箱全开放——每个人都能看基本面、技术面、消息面、资金面。性格决定了他们怎么处理信息，不是他们看什么信息。

## 三种交互模式

### 模式A — 赛马（每日收盘后）

海宁更新本地 kline CSV → "跑赛马" → 我用 Workflow 并行派出5个Agent → 每人读本地数据+bocha搜索+读自己MongoDB历史经验 → 做决策 → 写回MongoDB → 我汇总写简报

### 模式B — 随时对话

通过 `/agents` 注册5个持久化agent。海宁 `/agent 偏执狂` 直接切过去聊，聊完 `/agent 爱因斯坦` 切回来。对话数据和赛马数据互通。

### 模式C — 圆桌会议

赛马跑完后，我（爱因斯坦）主持讨论：

1. 我拉冲突摘要——分歧最大的点（同票不同方向、同一事实相反判断）
2. 我按顺序点名发言

```
我: "今天最大分歧在菲利华。偏执狂加仓了，赌徒卖了。偏执狂先说理由"
  → 派agent偏执狂发言 ← 基于他的持仓 + 我的问题
我: "赌徒，你听到了，反驳他"  
  → 派agent赌徒发言 ← 基于他的持仓 + 偏执狂的论点
我: "怀疑论者，你站哪边？"
  → 派agent怀疑论者发言
海宁随时插话提问
```

我不是主持人更是裁判，而是每次派一个agent发言，每个人基于前面的内容做回应。

## 五个角色

全员全源开放，性格决定如何处理信息。

### 1. 偏执狂
- 对自己判断极度自信，一旦买了就不轻易卖
- 好消息不让他更信，坏消息不让他更怕
- 撞的墙：死扛、认错慢、坐过山车
- 可累积经验：如何设置客观的认错条件

### 2. 机会主义者
- 灵活，哪个有钱赚去哪个，不执着
- 什么都看，不深看，决策靠"感觉"
- 撞的墙：没定力，震荡市两边打脸
- 可累积经验：什么时候该放弃灵活性

### 3. 怀疑论者
- 天然不信任何故事，专门找反面证据
- 撞的墙：过度悲观，系统性踏空
- 可累积经验：怀疑的边界在哪

### 4. 赌徒
- 不关心东西好不好，只关心赔率
- 只对极端值敏感
- 撞的墙：把归零当赔率优势，接飞刀
- 可累积经验：赔率计算的陷阱

### 5. 反省者
- 认知迭代优先于赚钱
- 不是找机会，是找"上次错的地方现在验证了/反驳了没"
- 撞的墙：过度内耗，为验证而交易
- 可累积经验：反思和行动的平衡点

### 角色互补

| 关键词 | 偏执狂 | 机会主义者 | 怀疑论者 | 赌徒 | 反省者 |
|--------|--------|------------|----------|------|--------|
| 面对信息 | 自信过滤 | 快速扫描 | 主动证伪 | 极端值敏感 | 对照历史 |
| 买入信号 | 深度验证后 | 感觉有戏 | 几乎不买 | 赔率到位 | 判断可验证 |
| 卖出信号 | 除非被迫 | 下一个机会 | 任何理由 | 目标到/止损到 | 判断被推翻 |
| 核心风险 | 死扛 | 没定力 | 踏空 | 接飞刀 | 内耗 |

## 数据流

海宁在Windows更新本地 kline CSV → 手动"跑赛马"

Agent 可直接使用：
1. 本地数据：`export/data/kline/*.csv` + profile/portfolio
2. 自己的 MongoDB 历史（持仓、交易、经验）
3. Bocha搜索当日新闻
4. Python工具（profile.py、scorer.py）

## 子任务输出格式

```json
{
  "agent_id": "pianzhikuang",
  "date": "2026-07-22",
  "market_judgment": {
    "direction": "bullish|bearish|sideways",
    "reason": "...",
    "confidence": 0-1
  },
  "operations": [
    {
      "type": "buy|sell", "code": "600000", "name": "...",
      "price": 12.34, "shares": 1000,
      "reason": "...", "planned_exit": "..."
    }
  ],
  "portfolio_snapshot": {
    "cash": 500000,
    "positions": [
      {"code": "600000", "name": "...", "shares": 1000, "cost": 12.0, "current": 12.34}
    ],
    "total_value": 980000,
    "daily_pnl_pct": 1.2
  },
  "retrospective": "今天学到/做错的..."
}
```

## 存储设计（MongoDB vocab 库）

### `agent_profiles`
5个agent身份和参数，一次性写入。

### `agent_sessions`
每场赛马一次 session：date, session_id("race_20260722"), agents[].

### `agent_trades`
交易流水：session_id, agent_id, action, code, name, price, shares, reason, pnl

### `agent_portfolios`
每日持仓快照：session_id, agent_id, cash, positions[], total_value, cumulative_pnl

### `agent_judgments`
判断记录：session_id, agent_id, direction, reason, confidence, retrospective

### `agent_experience`
**每个agent的经验积累。每次赛马/对话前先load出来作为上下文。**
agent_id, session_id, category(buy_signal|sell_signal|mistake|rule|insight), title, content, tags[], verified

原材料来自赛马时 retrospect 字段 → 我汇总时写入。不需要语义搜索，一把全拉出来即可。

### `agent_discussions`
对话记录：agent_id, date, topic, summary, key_points[]

## 经验积累归属

| 谁 | 存哪里 | 原因 |
|----|--------|------|
| 海宁 | stock-memory | 你的投资认知 |
| 爱因斯坦 | mem-search | 行为观察+赛马系统分析，不适合混入投资记忆 |
| 5个agent | agent_experience（MongoDB） | 每早精确load，不需要跨系统 |

## 独立 Web

路径：`/Users/hg26502/claude/agent_web/`

4个Tab：总览（资产曲线/当日操作）、持仓（明细/盈亏/集中度）、交易（流水/胜率）、回溯（判断 vs 走势/经验教训）

## 模拟交易规则

- 初始资金：100万/人
- 成交价：当日收盘价
- 成本：佣金万2.5 + 印花税千1
- 排除：ST、北交所

## 实施阶段

### Phase 1: 基础设施
- MongoDB 6个集合创建 + 建索引
- agent_profiles 写入5个角色
- Python辅助函数封装（kline CSV读取、profile调用）

### Phase 2: Agent 注册
- 写5套 system prompt（角色性格+可用工具+输出格式）
- prompt 同时支持三种模式：决策JSON / 自由对话 / 被点名回应
- 通过 `/agents` 注册5个持久化agent
- 配置 MCP 工具权限

### Phase 3: 赛马 Workflow
- Workflow 编排：我主持 → 5并行Agent → 汇总写入MongoDB
- 每个Agent执行时：读自己经验 → 读持仓 → 分析 → 写回
- 模拟交易规则实现

### Phase 4: 圆桌会议
- 我拉冲突摘要
- 按需派agent发言流程
- 议程模板

### Phase 5: Web
- 4个Tab

## 验证方式

1. 第一轮跑完 → MongoDB 数据完整
2. 5个agent差异明显
3. 圆桌会议有实质观点碰撞
4. Web 可查可用
