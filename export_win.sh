#!/bin/bash
# SSH 到 Windows 执行 K 线数据导出
set -e

echo "=== Windows 数据导出 ==="
ssh qjgeng@hg-win.local powershell -Command "E:\workspace\EasyXT\.venv\Scripts\python.exe E:\workspace\EasyXT\101factor\101factor_platform\src\factor_engine\demo_claw\financial_data\export\export_kline.py --full"
echo "导出完成"
