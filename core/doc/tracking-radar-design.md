# 跟踪雷达设计文档

> 跟踪列表 → 数据快照 → 搜索补充 → 完整报告

---

## 一、整体架构

```
┌───────────────────────────────────────────────┐
│ Web App「📡 跟踪雷达」tab                        │
│                                                │
│  1. Profile管理（增删改跟踪topic）               │
│     → 存取: core/dictionary/tracking_profiles.json│
│                                                │
│  2. 生成数据快照（拉本地parquet数据）             │
│     → 写入: 同上文件的 snapshot 段               │
│                                                │
│  3. 导出快照（供skill读取）                      │
└──────────────────────┬────────────────────────┘
                       │ 调用 skill
                       ▼
┌───────────────────────────────────────────────┐
│ Skill「跟踪雷达」                               │
│                                                │
│  1. 读 tracking_profiles.json                  │
│     - 读 profiles → 知道搜什么                  │
│     - 读 snapshot → 知道app已有什么              │
│                                                │
│  2. 对每个topic:                                │
│     - 按 search_keywords 搜博查                 │
│     - 按 check_points 验证                      │
│                                                │
│  3. 输出合并报告                                 │
└───────────────────────────────────────────────┘
```

---

## 二、数据文件

### 文件位置

`core/dictionary/tracking_profiles.json`

### 文件结构

```json
{
  "profiles": [
    {
      "name": "菲利华",
      "type": "stock",
      "code": "300395.SZ",
      "search_keywords": [
        "菲利华 军品认证",
        "菲利华 公告",
        "石英纤维 招标"
      ],
      "check_points": [
        "军品认证是否有新进展",
        "是否有大客户变动或订单公告",
        "季度业绩是否出预告"
      ]
    }
  ],

  "snapshot": {
    "generated_at": "2026-06-21T20:30:00",
    "app_version": "v1",
    "topics": {
      "菲利华": {
        "status": "ready",
        "data": {
          "price": { "ret_1w": -1.2, "ret_1m": -3.5, "ret_3m": 5.1, "ret_1y": 28.3 },
          "financial": { "rev_gr_2025": 15.2, "np_gr_2025": 22.1, "om_2025": 18.5, "roe_2025": 12.3 },
          "kline": { "ma20_above_ma60": true, "volume_1m_avg": 2.1e8, "volume_recent": 1.8e8 },
          "score": 9.5,
          "status": "绿灯"
        }
      }
    }
  }
}
```

**设计原则：**
- profiles 段是你维护的（增删改topic），只写不覆盖
- snapshot 段是app每次生成快照时重新写入的，每次覆盖
- skill 读这个文件，不做写入

---

## 三、三种 topic 类型

### stock 类型

| 字段 | 来源 | 说明 |
|------|------|------|
| code | app添加时选择 | 6位代码+.SZ/.SH |
| price 数据 | app从parquet拉 | 涨幅列，仅用于消息印证 |
| financial 数据 | app从parquet拉 | 营收增速/净利增速/ROE/评分 |
| **search_keywords** | 用户定义 + clue | 关键词是线索，skill决定如何展开搜索 |
| **check_points** | 用户定义 | 具体要验证的信号 |

> 价格数据不独立做技术分析，只作为消息的印证背景。

### futures 类型

| 字段 | 来源 | 说明 |
|------|------|------|
| name | 自由输入 | 如"黄金期货"、"白银" |
| app_data | **无本地数据** | 留null |
| search_keywords | 用户定义 | 搜价格/供需/地缘新闻 |
| check_points | 用户定义 | 具体要确认的信号 |

### macro 类型

| 字段 | 来源 | 说明 |
|------|------|------|
| name | 自由输入 | 如"美伊谈判"、"美联储" |
| app_data | **无本地数据** | 留null |
| search_keywords | 用户定义 | 搜相关新闻 |
| check_points | 用户定义 | 具体要确认的信号 |

---

## 四、Web App tab 设计

### 位置

现有4个tab后加第5个：`"📡 跟踪雷达"`

### 布局

```
┌─────────────────────────────────────────────────────┐
│ 侧边栏 (profile管理)            │ 主区域 (看板)        │
│                                                      │
│ ＋ 新增跟踪topic                  │                   │
│   select类型: stock/futures/macro  │ 表格:             │
│   → 根据类型展示不同表单            │ 名称 | 类型 | 状态  │
│      stock: 搜股票→选→填关键词     │ |1月|3月|评分     │
│      futures: 填名称+关键词        │ |最后更新|         │
│      macro: 填名称+关键词          │                   │
│                                 │ 点击行 → 展开详情    │
│  当前列表:                        │ ├ profile信息      │
│  □ 菲利华  stock  ✅              │ ├ 数据快照(如有)    │
│  □ 崇德科技 stock  ✅              │ └ 编辑关键词/要点   │
│  □ 黄金期货 futures ⏳             │                   │
│  □ 美伊谈判 macro  ⏳              │                   │
│  □ ...                           │ 底部操作:           │
│  [🗑 删除] [✎ 编辑]               │ [🔄 生成快照]       │
│                                 │   → 对每个stock topic│
│                                 │     拉parquet数据   │
│                                 │   → 写入snapshot段  │
│                                 │   → 显示完成状态     │
└─────────────────────────────────────────────────────┘
```

### 关键交互

**新增stock topic流程：**
1. 选择 type=stock
2. 输入股票代码/名称搜索（复用现有详情tab的搜索逻辑）
3. 点选匹配结果 → 自动补全 name + code
4. app 自动生成默认 search_keywords（基于name+SW2）
5. 用户可修改关键词和check_points
6. 保存 → 写入 profiles 段

**生成快照：**
- 遍历所有 type=stock 的 profile
- 对每个从 parquet 拉 price/financial/score 数据
- 写入 snapshot.topics 对应条目
- futures/macro 类型留 null

### 依赖

- `load_data()` — 已存在，读parquet
- `load_kline(code)` — 已存在，读K线
- `tracking_profiles.json` — 新增文件，app启动时加载

---

## 五、Skill「跟踪雷达」设计

### 调用方式

```
/跟踪雷达
```

### 安全约定

- skill 读 profiles.json，**不做写入**
- skill 输出直接写入 Obsidian vault：`2026/股市研究/跟踪雷达报告/`
- 每份报告以日期命名：`2026-06-21-跟踪雷达.md`

### 执行流程

```
1. 读 tracking_profiles.json
2. 对每个 profile:
   a. 从 snapshot 中取已有数据（作为背景）
   b. 对 search_keywords 逐条搜博查
   c. 针对 check_points 做验证
3. 输出合并报告
```

### 输出

结果直接写入 Obsidian vault：
```
/Users/hg26502/Library/Mobile Documents/iCloud~md~obsidian/Documents/Notes/
  2026/股市研究/跟踪雷达报告/2026-06-21-跟踪雷达.md
```

### 输出格式

```
# 📡 跟踪雷达报告 (2026-06-21)

## 📊 菲利华 (300395.SZ)

[app数据快照 — 股价背景]
  近1月: -3.5% | 近3月: +5.1% | 评分: 9.5 ✅
  营收增速(2025): +15.2% | 净利增速: +22.1%

[搜索 — 按线索展开]
  keyword "菲利华 公告" →
    ✅ 未发现新公告（上次6/10）
  keyword "军品认证" →
    ⚠️ 中国空军某型号配套认证在途，暂无公示进展
  keyword "石英纤维" →
    ✅ Q3招标量环比+30%（行业景气信号）

## 📊 黄金期货
[无本地数据]

  keyword "美伊局势 黄金" →
    ✅ 日内瓦协议已签，60天谈判窗口开启
    ⚠️ 以色列仍在轰炸黎巴嫩南部，变量未除
  keyword "黄金 价格" →
    当前 $4,150/oz，6周连跌，战争溢价持续消退
```

---

## 更新记录

- 2026-06-21: 初始设计
- 2026-06-21 修订: 
  - search_keywords 改为线索模式，skill 决定搜索展开方式  
  - 去掉 K 线技术分析，价格只作消息印证背景
  - skill 输出写入 Obsidian，不写回 JSON

## 六、实现优先级

### Phase 1 — App tab + profile管理 + 快照导出

| 模块 | 估算 |
|------|------|
| tracking_profiles.json 读写模块 | ~80行 |
| 新增topic表单（stock/futures/macro三种） | ~120行 |
| 看板表格 + 展开详情 | ~100行 |
| 快照生成逻辑（拉parquet数据） | ~60行 |
| 注册第5个tab | ~10行 |
| **合计 Phase 1** | **~370行** |

### Phase 2 — Skill

| 模块 | 估算 |
|------|------|
| 读取JSON + 解析profile | ~30行 |
| 按search_keywords搜博查 | ~50行 |
| 按check_points判断 + 输出报告 | ~80行 |
| **合计 Phase 2** | **~160行** |

---

## 七、设计决策（已定）

| 问题 | 决定 |
|------|------|
| search_keywords 粒度 | 关键词是线索，skill 决定如何展开搜索 |
| 快照是否含K线技术分析 | 否。价格只做消息印证背景，不独立分析 |
| skill输出写入哪里 | Obsidian vault `2026/股市研究/跟踪雷达报告/`
