#!/bin/bash
# SSH 到 Windows 执行 K 线数据下载
set -e

echo "=== Windows 数据下载 ==="
ssh qjgeng@hg-win.local powershell -Command "cd E:\workspace\EasyXT; E:\workspace\EasyXT\.venv\Scripts\python.exe E:\workspace\EasyXT\101factor\101factor_platform\src\factor_engine\demo_claw\financial_data\download_kline.py"
echo "下载完成"
