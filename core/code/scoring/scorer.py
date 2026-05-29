"""评分引擎。将 scoring/config.py 的规则应用到 profile DataFrame 上。"""

import pandas as pd
import numpy as np
from . import config


class Scorer:
    """对股票宽表应用评分规则，添加 score / status / 维度分 列。"""

    def __init__(self, rules=None, skip_by_sw1=None):
        self.rules = rules or config.RULES
        self.skip_by_sw1 = skip_by_sw1 or config.SKIP_BY_SW1
        self.dim_names = config.DIM_NAMES

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        输入：build_profile() 生成的宽表 DataFrame
        输出：原 DataFrame + 新增列:
          - score       总分 (0-10)
          - score_A~D   各维度分 (0-10)
          - status      绿灯/黄灯/红灯
        """
        df = df.copy()

        dim_max_deduct = self._calc_dim_max_deduct()
        dim_scores = {d: [] for d in dim_max_deduct}

        for idx, row in df.iterrows():
            sw1 = row.get("SW1")
            dim_deduct = {d: 0 for d in dim_max_deduct}

            for rule in self.rules:
                label = rule["label"]
                dim = rule["dim"]

                # 行业例外跳过
                if sw1 in self.skip_by_sw1 and label in self.skip_by_sw1[sw1]:
                    continue

                val = row.get(rule["col"])
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    continue

                if rule["cond"](val):
                    dim_deduct[dim] += rule["deduct"]

            for d, deduct in dim_deduct.items():
                # 维度分 = max(10 - 扣分, 0)
                dim_scores[d].append(max(10 - deduct, 0))

        for d in dim_max_deduct:
            df[f"score_{d}"] = dim_scores[d]

        # 总分 = 各维度平均
        dim_cols = [f"score_{d}" for d in dim_max_deduct]
        df["score"] = df[dim_cols].mean(axis=1).round(1)

        # 状态
        def _status(s):
            if pd.isna(s):
                return "NA"
            if s >= 8:
                return "绿灯"
            elif s >= 5:
                return "黄灯"
            return "红灯"

        df["status"] = df["score"].map(_status)

        return df

    def _calc_dim_max_deduct(self) -> dict:
        """计算每个维度的最大可能扣分，用于归一化（当前是硬扣分，暂不归一）。"""
        dim_max = {}
        for rule in self.rules:
            d = rule["dim"]
            dim_max[d] = dim_max.get(d, 0) + rule["deduct"]
        return dim_max
