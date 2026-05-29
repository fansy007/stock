# -*- coding: utf-8 -*-
"""
全A股申万行业分类导出脚本（SW1 一级 + SW2 二级）

输出: export/data/sw_industry.csv
  字段: stock_code, stock_name, SW1, SW2

使用方式:
    python export_sw_industry.py              # 全量导出
    python export_sw_industry.py --sample 10   # 测试模式: 仅处理前 N 只股票
"""
import sys
import os
import json
import importlib.util
from datetime import datetime
import time

import pandas as pd

# ============================================================
# 路径定义
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # demo_claw
XTQUANT_PATH = os.path.join(PROJECT_ROOT, '..', 'xtquant')
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
OUTPUT_FILE = os.path.join(DATA_DIR, 'sw_industry.csv')
ERROR_LOG = os.path.join(SCRIPT_DIR, 'export_errors.log')


# ============================================================
# xtquant 加载
# ============================================================
def load_xtquant():
    """加载 xtquant 和 xtdata 模块"""
    for key in list(sys.modules.keys()):
        if 'xtquant' in key:
            del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        'xtquant', os.path.join(XTQUANT_PATH, '__init__.py'))
    xtquant = importlib.util.module_from_spec(spec)
    sys.modules['xtquant'] = xtquant
    spec.loader.exec_module(xtquant)

    xtdata_spec = importlib.util.spec_from_file_location(
        'xtquant.xtdata', os.path.join(XTQUANT_PATH, 'xtdata.py'))
    xtdata = importlib.util.module_from_spec(xtdata_spec)
    sys.modules['xtquant.xtdata'] = xtdata
    xtdata_spec.loader.exec_module(xtdata)

    return xtquant, xtdata


def log_error(msg):
    with open(ERROR_LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')


# ============================================================
# 核心: 构建申万行业映射
# ============================================================
def build_sw_mapping(xtdata, stock_list):
    """
    构建 stock_code -> (SW1, SW2) 的映射。
    所有入参的 stock_code 都是完整格式，如 '000001.SZ'。
    """
    print("下载板块数据...")
    xtdata.download_sector_data()

    sectors = xtdata.get_sector_list()

    # ---- SW1 一级行业 ----
    sw1_sectors = sorted([s for s in sectors if s.startswith('SW1') and '加权' not in s])
    print(f"申万一级行业（SW1）: {len(sw1_sectors)} 个")

    stock_to_sw1 = {}
    for sector in sw1_sectors:
        stocks = xtdata.get_stock_list_in_sector(sector)
        for s in stocks:
            if s not in stock_to_sw1:
                stock_to_sw1[s] = sector.replace('SW1', '')

    # ---- SW2 二级行业 ----
    sw2_sectors = sorted([s for s in sectors if s.startswith('SW2') and '加权' not in s])
    print(f"申万二级行业（SW2）: {len(sw2_sectors)} 个")

    stock_to_sw2 = {}
    for sector in sw2_sectors:
        stocks = xtdata.get_stock_list_in_sector(sector)
        for s in stocks:
            if s not in stock_to_sw2:
                stock_to_sw2[s] = sector.replace('SW2', '')

    # ---- 构建目标股票列表的映射 ----
    sw1_list = []
    sw2_list = []
    missing_sw1 = 0
    missing_sw2 = 0

    for stock in stock_list:
        s1 = stock_to_sw1.get(stock, '')
        s2 = stock_to_sw2.get(stock, '')
        sw1_list.append(s1)
        sw2_list.append(s2)
        if not s1:
            missing_sw1 += 1
        if not s2:
            missing_sw2 += 1

    if missing_sw1:
        print(f"  无SW1归属: {missing_sw1}/{len(stock_list)}")
    if missing_sw2:
        print(f"  无SW2归属: {missing_sw2}/{len(stock_list)}")

    return sw1_list, sw2_list


def get_stock_names(xtdata, stock_list, batch_size=200):
    """逐个获取股票名称"""
    names = []
    total = len(stock_list)
    for i in range(0, total, batch_size):
        batch = stock_list[i:i + batch_size]
        for stock in batch:
            try:
                detail = xtdata.get_instrument_detail(stock)
                if detail and isinstance(detail, dict):
                    names.append(detail.get('InstrumentName', ''))
                else:
                    names.append('')
            except Exception:
                names.append('')
        if (i + batch_size) % 1000 == 0 or (i + batch_size) >= total:
            print(f"  获取股票名称: {min(i + batch_size, total)}/{total}")
    return names


# ============================================================
# 主流程
# ============================================================
def main():
    sample_mode = False
    sample_n = 0
    if '--sample' in sys.argv:
        idx = sys.argv.index('--sample')
        sample_n = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 10
        sample_mode = True
        print(f"测试模式: 仅处理前 {sample_n} 只股票")

    print("加载 xtquant...")
    xtquant, xtdata = load_xtquant()

    print("获取全A股列表...")
    stocks = xtdata.get_stock_list_in_sector('沪深A股')
    stocks = sorted(stocks)
    print(f"全A股总数: {len(stocks)}")

    if sample_mode and sample_n > 0:
        stocks = stocks[:sample_n]
        print(f"测试模式取样: {len(stocks)} 只股票")

    # 获取股票名称
    print("获取股票名称...")
    stock_names = get_stock_names(xtdata, stocks)

    # 构建申万行业映射
    print("构建申万行业映射...")
    t0 = time.time()
    sw1_list, sw2_list = build_sw_mapping(xtdata, stocks)
    print(f"行业映射耗时: {time.time() - t0:.1f}s")

    # 组装 DataFrame
    df = pd.DataFrame({
        'stock_code': stocks,
        'stock_name': stock_names,
        'SW1': sw1_list,
        'SW2': sw2_list,
    })

    # 输出
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"\n输出文件: {OUTPUT_FILE}")
    print(f"记录数: {len(df)}")

    # 统计摘要
    print(f"\n{'='*50}")
    print("SW1 行业分布（TOP 10）:")
    sw1_stats = df['SW1'].value_counts()
    total_with_sw1 = (df['SW1'] != '').sum()
    for ind, cnt in sw1_stats.head(10).items():
        print(f"  {ind}: {cnt}")
    print(f"  有SW1归属: {total_with_sw1}/{len(df)}")

    print(f"\nSW2 行业分布（TOP 10）:")
    sw2_stats = df['SW2'].value_counts()
    total_with_sw2 = (df['SW2'] != '').sum()
    for ind, cnt in sw2_stats.head(10).items():
        print(f"  {ind}: {cnt}")
    print(f"  有SW2归属: {total_with_sw2}/{len(df)}")

    print(f"\n导出完成！")


if __name__ == '__main__':
    main()
