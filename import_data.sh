#!/bin/bash
# 从 Windows 拉取 K 线数据 → 刷新评分缓存
set -e

echo "=== 从 Windows 拉取 K 线数据 ==="
echo "(正在传输 5209 个文件，约 30-60 秒...)"
ssh qjgeng@hg-win.local powershell -Command "cd 'E:\workspace\EasyXT\101factor\101factor_platform\src\factor_engine\demo_claw\financial_data\export\data\kline'; tar czf - *.csv" | tar xzf - -C /Users/hg26502/claude/stock/export/data/kline/
echo "K 线数据更新完成"

echo ""
echo "=== 刷新评分缓存 ==="
python3 -c "
from core.code.profile import build_profile
from core.code.scoring.scorer import Scorer

df = build_profile(refresh=True)
df = Scorer().apply(df)
df.to_parquet('core/dictionary/stock_profile.parquet', index=False)

n = len(df)
green = (df['status'] == '绿灯').sum()
yellow = (df['status'] == '黄灯').sum()
red = (df['status'] == '红灯').sum()
print(f'缓存刷新完成: 共 {n} 只股票, 绿灯 {green}, 黄灯 {yellow}, 红灯 {red}')
"
