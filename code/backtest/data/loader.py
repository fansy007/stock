"""
K线数据加载器

从 export/data/kline/ 批量加载日线 CSV 到内存 DataFrame，
格式对齐 Alpha101Factors 要求的 MultiIndex (date, symbol)。
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional


def load_kline_data(stock_list: list,
                    start_date: str,
                    end_date: str,
                    kline_dir: str = None) -> pd.DataFrame:
    """批量加载 K 线数据

    从 export/data/kline/ 读取指定股票列表的 CSV，
    过滤日期范围，返回 MultiIndex DataFrame。

    Args:
        stock_list: 股票代码列表
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
        kline_dir: K线CSV目录，默认从项目路径推算

    Returns:
        DataFrame with MultiIndex (date, symbol), columns=[open, high, low, close, volume]
    """
    if kline_dir is None:
        kline_dir = _default_kline_dir()

    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    all_parts = []
    loaded = 0
    missing = 0

    for stock in stock_list:
        fp = os.path.join(kline_dir, f'{stock}.csv')
        if not os.path.exists(fp):
            missing += 1
            continue
        try:
            df = pd.read_csv(fp)
            if df.empty:
                continue
            # 确保 time 列存在
            if 'time' not in df.columns:
                continue
            # 转换时间戳
            df['date'] = pd.to_datetime(df['time'], unit='ms').dt.normalize()
            # 过滤日期范围
            df = df[(df['date'] >= start_dt) & (df['date'] < end_dt)]
            if df.empty:
                continue
            df['symbol'] = stock
            # 只取需要的列
            cols = ['date', 'symbol', 'open', 'high', 'low', 'close', 'volume']
            df = df[[c for c in cols if c in df.columns]]
            all_parts.append(df)
            loaded += 1
        except Exception:
            missing += 1
            continue

    if not all_parts:
        print(f"[数据加载] 未加载到任何数据 (请求{len(stock_list)}只)")
        return pd.DataFrame()

    result = pd.concat(all_parts, ignore_index=True)
    result = result.set_index(['date', 'symbol']).sort_index()

    # 确保列是数值型
    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors='coerce')

    print(f"[数据加载] 加载 {loaded}/{len(stock_list)} 只股票, "
          f"{result.shape[0]} 行, "
          f"日期 {result.index.get_level_values('date').min().strftime('%Y%m%d')}"
          f" ~ {result.index.get_level_values('date').max().strftime('%Y%m%d')}")
    if missing:
        print(f"[数据加载] {missing} 只股票无K线文件")

    return result


def load_kline_single(stock: str, kline_dir: str = None) -> pd.DataFrame:
    """加载单只股票的完整 K 线数据

    Args:
        stock: 股票代码
        kline_dir: K线CSV目录

    Returns:
        DataFrame with columns=[time, open, high, low, close, volume],
        date 列为 datetime 索引
    """
    if kline_dir is None:
        kline_dir = _default_kline_dir()

    fp = os.path.join(kline_dir, f'{stock}.csv')
    if not os.path.exists(fp):
        return pd.DataFrame()

    df = pd.read_csv(fp)
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['time'], unit='ms').dt.normalize()
    df = df.set_index('date').sort_index()
    return df


def get_trading_dates(start_date: str, end_date: str) -> list:
    """获取交易日历

    从已有K线数据中推断交易日（不含周末和节假日）。

    Args:
        start_date: YYYYMMDD
        end_date: YYYYMMDD

    Returns:
        日期字符串列表 ['20260101', ...]
    """
    # 从 stock_list.csv 中随便取一只股票来获取交易日
    kline_dir = _default_kline_dir()
    stock_list_path = os.path.join(
        os.path.dirname(kline_dir), 'stock_list.csv')
    if os.path.exists(stock_list_path):
        try:
            df = pd.read_csv(stock_list_path)
            stock = df.iloc[0, 0]
            kdata = load_kline_single(stock, kline_dir)
            if not kdata.empty:
                dates = kdata[(kdata.index >= pd.Timestamp(start_date)) &
                              (kdata.index <= pd.Timestamp(end_date))]
                return [d.strftime('%Y%m%d') for d in dates.index]
        except Exception:
            pass

    # 回退：按工作日生成
    start = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    dates = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            dates.append(cur.strftime('%Y%m%d'))
        cur += timedelta(days=1)
    return dates


def _default_kline_dir() -> str:
    """获取默认 K 线目录"""
    from pathlib import Path
    return str(Path(__file__).resolve().parent.parent.parent.parent /
               'export' / 'data' / 'kline')


# 避免 timedelta 未被识别
from datetime import timedelta


def load_stock_list(csv_path: str = None) -> list:
    """加载股票列表"""
    if csv_path is None:
        csv_path = os.path.join(
            os.path.dirname(_default_kline_dir()), 'stock_list.csv')
    if not os.path.exists(csv_path):
        return []
    try:
        df = pd.read_csv(csv_path)
        return df.iloc[:, 0].dropna().str.strip().tolist()
    except Exception:
        return []
