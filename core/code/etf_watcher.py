"""
ETF 国家队监视器 — 从数据里直接看国家队动向

数据源：东方财富 push2his.eastmoney.com (无需认证, 免费)

用法：
    from core.code.etf_watcher import EtfWatcher

    w = EtfWatcher()
    report = w.analyze()
    print(report)

技术说明：用 urllib.request 绕过 macOS 系统代理（ClashX/Surge），
requests 库会因 urllib3 读取系统代理设置而失败。
"""

import json
import ssl
import urllib.request
from datetime import datetime, timedelta

import certifi

# 主要宽基ETF监控列表
DEFAULT_ETF = {
    "510300": "沪深300ETF(华泰柏瑞)",
    "510050": "上证50ETF(华夏)",
    "510500": "中证500ETF(南方)",
    "588000": "科创50ETF(华夏)",
}

# 辅助ETF（交叉验证用）
EXTRA_ETF = {
    "159919": "沪深300ETF(嘉实)",
    "510310": "沪深300ETF(易方达)",
}

# 全局复用 opener：绕过 macOS 系统代理 + certifi SSL
_CTX = ssl.create_default_context(cafile=certifi.where())
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=_CTX),
)


def _fetch_json(url: str, timeout: int = 10) -> dict:
    """GET JSON，绕过系统代理"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = _OPENER.open(req, timeout=timeout)
    return json.loads(resp.read())


class EtfWatcher:
    """ETF 国家队监控"""

    def fetch_kline(self, code: str, days: int = 30) -> list[dict]:
        """获取ETF日K线数据"""
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid=1.{code}"
            f"&fields1=f1,f2,f3"
            f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
            f"&klt=101&fqt=1"
            f"&end={datetime.now().strftime('%Y%m%d')}"
            f"&lmt={days}"
        )
        data = _fetch_json(url)

        rows = []
        if data.get("data") and data["data"].get("klines"):
            for line in data["data"]["klines"]:
                parts = line.split(",")
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(parts[5]),
                    "amount": float(parts[6]),
                })
        return rows

    def calc_volume_ma(self, rows: list[dict], window: int = 5) -> float:
        """计算最近 N 天(不含今天)的日均成交额"""
        vals = [r["amount"] for r in rows[-(window + 1):-1]]
        return sum(vals) / len(vals) if vals else 0

    def detect_anomalies(self, rows: list[dict]) -> list[dict]:
        """检测成交额异常交易日"""
        if len(rows) < 6:
            return []

        anomalies = []
        for i in range(1, len(rows)):
            r = rows[i]
            prev_rows = rows[max(0, i - 5):i]
            ma = sum(p["amount"] for p in prev_rows) / len(prev_rows)

            ratio = round(r["amount"] / ma, 2) if ma > 0 else 1
            level = ""
            if ratio >= 3.0:
                level = "极端放量"
            elif ratio >= 2.0:
                level = "显著放量"
            elif ratio >= 1.5:
                level = "放量"

            if level:
                direction = "涨" if r["close"] >= r["open"] else "跌"
                anomalies.append({
                    "date": r["date"],
                    "amount_billion": round(r["amount"] / 1e8, 1),
                    "ma5_billion": round(ma / 1e8, 1),
                    "ratio": ratio,
                    "level": level,
                    "direction": direction,
                    "pct_change": round((r["close"] - r["open"]) / r["open"] * 100, 2),
                    "close": r["close"],
                })
        return anomalies

    def analyze_single(self, code: str, name: str, rows: list[dict] | None = None) -> dict:
        """分析单个ETF"""
        if rows is None:
            rows = self.fetch_kline(code, days=30)

        if not rows:
            return {"code": code, "name": name, "error": "无数据"}

        latest = rows[-1]
        ma5 = self.calc_volume_ma(rows, window=5)
        anomalies = self.detect_anomalies(rows)

        amounts = [r["amount"] for r in rows]
        today_rank = sum(1 for a in amounts if a < latest["amount"]) + 1
        total_days = len(amounts)

        return {
            "code": code,
            "name": name,
            "latest_price": latest["close"],
            "today_amount_billion": round(latest["amount"] / 1e8, 1),
            "today_volume": latest["volume"],
            "today_direction": "涨" if latest["close"] >= latest["open"] else "跌",
            "today_pct": round((latest["close"] - latest["open"]) / latest["open"] * 100, 2),
            "ma5_amount_billion": round(ma5 / 1e8, 1),
            "amount_rank": f"{today_rank}/{total_days}",
            "vs_ma5_ratio": round(latest["amount"] / ma5, 2) if ma5 > 0 else 0,
            "anomalies": anomalies,
            "recent_7d": [
                {
                    "date": r["date"],
                    "close": r["close"],
                    "amount_billion": round(r["amount"] / 1e8, 1),
                }
                for r in rows[-7:]
            ],
        }

    def analyze(self, etf_list: dict[str, str] | None = None) -> dict:
        """全部分析"""
        etf_list = etf_list or DEFAULT_ETF

        results = {}
        for code, name in etf_list.items():
            try:
                rows = self.fetch_kline(code, days=30)
                results[code] = self.analyze_single(code, name, rows)
            except Exception as e:
                results[code] = {"code": code, "name": name, "error": str(e)}

        sync_dates = self._detect_sync_buying(results)

        return {
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "etfs": results,
            "sync_signals": sync_dates,
            "today_flag": self._judge_today(results),
        }

    def _detect_sync_buying(self, results: dict) -> list[dict]:
        """检测多ETF同步放量"""
        date_map: dict[str, list[dict]] = {}
        for code, r in results.items():
            for a in r.get("anomalies", []):
                d = a["date"]
                date_map.setdefault(d, []).append({"code": code, **a})

        syncs = []
        for date, items in sorted(date_map.items()):
            sig_count = len([it for it in items if it["level"] in ("显著放量", "极端放量")])
            normal_count = len([it for it in items if it["level"] == "放量"])
            if sig_count >= 2 or (sig_count + normal_count) >= 3:
                syncs.append({
                    "date": date,
                    "trigger_count": len(items),
                    "sig_count": sig_count,
                    "details": items,
                    "avg_pct_change": round(
                        sum(it["pct_change"] for it in items) / len(items), 2
                    ),
                })
        return sorted(syncs, key=lambda x: x["date"])

    def _judge_today(self, results: dict) -> dict:
        """判断今天是否有国家队买入迹象"""
        signals = []

        for code, r in results.items():
            ratio = r.get("vs_ma5_ratio", 0)
            if ratio >= 1.5:
                signals.append(f"{r['name']}放量(均量{r['ma5_amount_billion']}亿→今日{r['today_amount_billion']}亿, ×{ratio})")

        today_sig_count = sum(1 for r in results.values() if r.get("vs_ma5_ratio", 0) >= 2.0)
        today_count = sum(1 for r in results.values() if r.get("vs_ma5_ratio", 0) >= 1.5)

        if today_sig_count >= 3:
            confidence = "高"
        elif today_count >= 3:
            confidence = "中高"
        elif today_count >= 2:
            confidence = "中"
        else:
            confidence = "低"

        return {"signal_count": len(signals), "confidence": confidence, "signals": signals}

    def report(self, etf_list: dict[str, str] | None = None) -> str:
        """生成文本报告"""
        data = self.analyze(etf_list)
        lines = []
        lines.append("# 国家队ETF动向监测")
        lines.append(f"**时间：**{data['fetched_at']}")
        lines.append(f"**今日判断：**{'⚠️ 有信号' if data['today_flag']['signals'] else '无异常'}")
        if data['today_flag']['signals']:
            lines.append(f"**置信度：**{data['today_flag']['confidence']}")
            lines.append(f"\n**信号详情：**")
            for s in data['today_flag']['signals']:
                lines.append(f"- {s}")
        lines.append("")

        for code, r in data["etfs"].items():
            if r.get("error"):
                lines.append(f"## {r['name']}({code}) — ❌ {r['error']}")
                continue

            lines.append(f"## {r['name']}({code})")
            lines.append(f"现价:{r['latest_price']} 今日:{r['today_direction']}{abs(r['today_pct']):.2f}%")
            lines.append(f"成交额:{r['today_amount_billion']}亿 | 近5日均值:{r['ma5_amount_billion']}亿 | ×{r['vs_ma5_ratio']}倍")

            if r["anomalies"]:
                lines.append("\n**异常放量日：**")
                for a in reversed(r["anomalies"]):
                    marker = " 🔴" if a["level"] == "极端放量" else " 🟡" if a["level"] == "显著放量" else ""
                    lines.append(
                        f"- {a['date']} {a['level']}{marker}: "
                        f"成交{a['amount_billion']}亿(均量{a['ma5_billion']}亿, ×{a['ratio']}) "
                        f"收{a['close']} {a['direction']}{abs(a['pct_change']):.2f}%"
                    )

            lines.append(f"\n**最近7天成交额：**")
            for d in reversed(r["recent_7d"][-7:]):
                bar = "█" * max(1, int(d["amount_billion"] / 5))
                lines.append(f"  {d['date']} {d['amount_billion']:>5.1f}亿 {bar}")
            lines.append("")

        if data["sync_signals"]:
            lines.append("---")
            lines.append("## 多ETF同步放量（国家队特征）")
            for s in data["sync_signals"]:
                lines.append(f"\n**{s['date']}** — {s['trigger_count']}只ETF异常 ({s['sig_count']}只显著)")
                lines.append(f"  当日各ETF平均涨跌: {s['avg_pct_change']:.2f}%")
                for d in s["details"]:
                    lines.append(f"  - {d['code']} {d['level']} ({d['direction']}{abs(d['pct_change']):.2f}%)")
            lines.append("")

        return "\n".join(lines)


if __name__ == "__main__":
    print(EtfWatcher().report())
