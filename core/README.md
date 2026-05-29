# stock/core — A 股分析引擎

5207 只股票的 5 年财务 + K 线 + 概念/行业宽表，一键生成。

## 快速上手

```python
from core.code.profile import build_profile
from core.code.scoring import Scorer

# 生成数据（首次 6s，后续读缓存 0.1s）
df = build_profile(refresh=False)

# 加评分
df = Scorer().apply(df)

# === 常用筛选模式 ===

# 按行业 + 财务条件
mask = (df['SW1'] == '电子') & (df['rev_gr_2025'] > 15) & (df['om_2025'] > 10)
df[mask][['name','rev_2025','rev_gr_2025','om_2025','score','status']]

# 按概念（字符串包含）
ai = df[df['concepts'].str.contains('低空经济', na=False)]

# 概念交叉（多个概念同时出现）
pcb_fiber = df[df['concepts'].str.contains('PCB概念', na=False) &
               df['concepts'].str.contains('光纤概念', na=False)]

# 背离信号：财务好转 + 股价没涨
screening = df[(df['rev_gr_2025'] > 15) & (df['om_chg_2025'] > 0) &
               (df['roe_2025'] > 8) & (df['ret_1y'] < 20)]
```

## 强制刷新

```python
# 数据更新后重新计算
df = build_profile(refresh=True)
```

## 数据结构

### 行：5207 只 A 股（沪深主板+创业板+科创板，已剔除北交所）

### 列：111 列

| 分组 | 列数 | 内容 |
|------|------|------|
| 基础信息 | 5 | stock_code, name, SW1, SW2, concepts |
| 年度指标 | 101 | rev/np/om/roe/ocf/ar/inv/ar_inv/ap/advance/ar_inv_prep — 2021~2025 各年值 + 增速/变化 |
| 最新季度 | 14 | q_rev/q_np/q_ar/q_inv/q_ap/q_advance 及同比 |
| 安全指标 | 5 | debt_ratio, int_cvg, ar_inv_prep_to_rev, gw_ratio, cf_to_np |
| 价格收益 | 8 | ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, ret_2y, ret_3y, ret_5y |
| 评分 | 6 | score, score_A~D, status |

### 关键指标速查

| 列名 | 说明 | 数据源 |
|------|------|--------|
| rev_2025 | 2025 营收（亿元） | Income 年报 |
| rev_gr_2025 | 营收同比（%） | 计算 |
| np_2025 | 2025 归母净利润（亿元） | Income 年报 |
| np_gr_2025 | 净利同比（%） | 计算 |
| om_2025 | 营业利润率 = oper_profit / revenue（%） | Income 年报(计算) |
| om_chg_2025 | 营业利润率变化（百分点） | 计算 |
| roe_2025 | ROE = np / 净资产（%） | Income + Balance |
| ocf_2025 | 经营现金流净额（亿元） | CashFlow 年报 |
| ocf_gr_2025 | 经营现金流同比（%） | 计算 |
| ar_inv_2025 | 应收+存货（亿元） | Balance |
| ar_inv_gr_2025 | 应收+存货同比（%） | 计算 |
| ap_2025 | 应付账款（亿元） | Balance |
| debt_ratio | 资产负债率（%） | Balance 最新 |
| int_cvg | 利息覆盖倍数 | Income 最新年报 |
| ar_inv_prep_to_rev | 应收+存货+预付/营收（%） | Balance + Income |
| gw_ratio | 商誉/净资产（%） | Balance |
| cf_to_np | 经营现金流/归母净利 | CashFlow + Income |

## 评分机制

### 四维度扣分制

| 维度 | 名称 | 满分 | 规则数 | 说明 |
|------|------|------|--------|------|
| A | 盈利质量 | 10 | 6 | 营收/净利增长、利润率水平 |
| B | 现金流安全 | 10 | 3 | 经营现金流、利润含金量 |
| C | 资产质量 | 10 | 4 | 负债率、利息覆盖、应收存货 |
| D | 破绽 | 10 | 1 | 商誉风险 |

总分 = (score_A + score_B + score_C + score_D) / 4

### 规则明细

每条规则扣分制：满足条件则扣对应分数，维度分 = max(10 - 扣分, 0)。

| 维度 | 规则 | 列名 | 条件 | 扣分 |
|------|------|------|------|------|
| A | 营收萎缩 | rev_gr_2025 | < 0 | 2 |
| A | 营收低增长 | rev_gr_2025 | 0~10 | 1 |
| A | 归母亏损 | np_2025 | < 0 | 3 |
| A | 净利下滑 | np_gr_2025 | < 0 | 1 |
| A | 利润率恶化 | om_chg_2025 | < -3 百分点 | 2 |
| A | 利润率过低 | om_2025 | < 5% | 1 |
| B | 经营失血 | ocf_2025 | < 0 | 2 |
| B | 利润含金量低 | cf_to_np | 0~0.5 | 1 |
| B | 现金流恶化 | ocf_gr_2025 | < -20% | 1 |
| C | 高负债 | debt_ratio | > 70% | 2 |
| C | 还息吃力 | int_cvg | 0~1.5 | 2 |
| C | 利息无法覆盖 | int_cvg | <= 0 | 3 |
| C | 应收+存货增速远超营收 | ar_inv_gr_2025 | > 30% | 1 |
| D | 商誉风险 | gw_ratio | > 20% | 2 |

### 行业例外

金融行业部分指标不适用，已在评分中跳过：

- **银行**：跳过营收相关、现金流相关、应收存货共 8 条规则
- **非银金融**：跳过营收相关、应收存货共 5 条规则

### 状态

| 评分范围 | 状态 | 含义 |
|---------|------|------|
| >= 8 | 绿灯 | 基本面良好 |
| 5~7 | 黄灯 | 有值得注意的扣分项 |
| < 5 | 红灯 | 明显问题 |

## 数据流

```
export/data/
  Income.csv         ← 只读，Windows 增量更新
  CashFlow.csv       ← 只读
  Balance.csv        ← 只读
  kline/*.csv        ← 只读

core/dictionary/
  stock_profile.json  ← 行业+概念映射表（手动更新）
  stock_profile.parquet ← build_profile() 缓存
  stock_profile_meta.json ← 缓存元信息（built_at）

core/code/
  profile.py          ← build_profile()
  scoring/
    config.py          ← 评分规则定义（可调）
    scorer.py          ← Scorer 类
```

## 注意事项

- `cost_of_goods_sold` 字段全空，毛利率无法计算。用营业利润率替代。
- 北交所股票已剔除（无申万分类）。
- 金融行业（银行/非银金融）部分指标不适用，scoring 中已跳过。
- 新股上市不满 5 年的，对应年份和 ret 列标为 NaN。
- 概念筛选用 `str.contains`，注意可能误匹配（如概念名包含关系）。
