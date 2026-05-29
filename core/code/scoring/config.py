"""
评分规则定义。

每条规则是一个 dict，包含：
  - col:     DataFrame 中的列名（或对列的计算表达式）
  - label:   规则名称（用于日志/展示）
  - cond:    触发扣分的条件函数 (value: float) -> bool
  - deduct:  扣分数
  - dim:     所属维度 (A=盈利质量, B=现金流安全, C=资产质量, D=破绽)

例外行业：SW1 在 SKIP_BY_SW1 中的，跳过指定 label 的规则。
"""

# (col, label, cond_deduct, dim) 四元组
# cond_deduct = (condition_function, score_to_deduct)
# condition_function takes the value from the column

RULES = [
    # ===== 维度 A: 盈利质量 =====
    dict(col="rev_gr_2025", label="营收萎缩",
         cond=lambda v: v is not None and v < 0, deduct=2, dim="A"),
    dict(col="rev_gr_2025", label="营收低增长",
         cond=lambda v: v is not None and 0 <= v < 10, deduct=1, dim="A"),
    dict(col="np_2025", label="归母亏损",
         cond=lambda v: v is not None and v < 0, deduct=3, dim="A"),
    dict(col="np_gr_2025", label="净利下滑",
         cond=lambda v: v is not None and v < 0, deduct=1, dim="A"),
    dict(col="om_chg_2025", label="利润率恶化",
         cond=lambda v: v is not None and v < -3, deduct=2, dim="A"),
    dict(col="om_2025", label="利润率过低",
         cond=lambda v: v is not None and v < 5, deduct=1, dim="A"),

    # ===== 维度 B: 现金流安全 =====
    dict(col="ocf_2025", label="经营失血",
         cond=lambda v: v is not None and v < 0, deduct=2, dim="B"),
    dict(col="cf_to_np", label="利润含金量低",
         cond=lambda v: v is not None and 0 < v < 0.5, deduct=1, dim="B"),
    dict(col="ocf_gr_2025", label="现金流恶化",
         cond=lambda v: v is not None and v < -20, deduct=1, dim="B"),

    # ===== 维度 C: 资产质量 =====
    dict(col="debt_ratio", label="高负债",
         cond=lambda v: v is not None and v > 70, deduct=2, dim="C"),
    dict(col="int_cvg", label="还息吃力",
         cond=lambda v: v is not None and 0 < v < 1.5, deduct=2, dim="C"),
    dict(col="int_cvg", label="利息无法覆盖",
         cond=lambda v: v is not None and v <= 0, deduct=3, dim="C"),
    dict(col="ar_inv_gr_2025", label="应收+存货增速远超营收",
         cond=lambda v: v is not None and v > 30, deduct=1, dim="C"),

    # ===== 维度 D: 破绽 =====
    dict(col="gw_ratio", label="商誉风险",
         cond=lambda v: v is not None and v > 20, deduct=2, dim="D"),
]

# 按行业跳过规则。value 是 label 列表
SKIP_BY_SW1 = {
    "银行":     ["营收萎缩", "营收低增长", "利润率恶化", "利润率过低",
                "经营失血", "现金流恶化", "利润含金量低",
                "应收+存货增速远超营收"],
    "非银金融":  ["营收萎缩", "营收低增长", "利润率恶化", "利润率过低",
                "应收+存货增速远超营收"],
}

# 维度名称
DIM_NAMES = {
    "A": "盈利质量",
    "B": "现金流安全",
    "C": "资产质量",
    "D": "破绽",
}
