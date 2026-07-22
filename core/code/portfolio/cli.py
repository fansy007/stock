#!/usr/bin/env python3
"""投资组合日终日志 CLI — 记录每日总资产/持仓/成交。"""

import argparse
import json
import sys
from datetime import datetime

from core.code.portfolio.db import (
    create_log,
    get_log,
    get_log_by_date,
    list_logs,
    update_log,
    delete_log,
    latest_log,
)


def cmd_add(args):
    holdings = _load_json_array(args.holdings_json, args.holdings_file)
    trades = _load_json_array(args.trades_json, args.trades_file)
    pid = create_log(
        date=args.date,
        total_assets=args.total_assets,
        market_value=args.market_value,
        total_pnl=args.total_pnl,
        daily_pnl=args.daily_pnl,
        cash_balance=args.cash_balance,
        withdrawable=args.withdrawable,
        available=args.available,
        holdings=holdings,
        trades=trades,
    )
    print(pid)


def cmd_get(args):
    p = get_log(args.id)
    if not p:
        print("[]", file=sys.stderr)
        sys.exit(1)
    _to_json(p)


def cmd_get_by_date(args):
    p = get_log_by_date(args.date)
    if not p:
        print("[]", file=sys.stderr)
        sys.exit(1)
    _to_json(p)


def cmd_list(args):
    docs = list_logs(
        date_from=args.date_from,
        date_to=args.date_to,
        sort=args.sort,
        limit=args.limit,
    )
    if args.format == "json":
        _to_json(docs)
    else:
        _print_table(docs)


def cmd_update(args):
    updates = {}
    for k in ("total_assets", "market_value", "total_pnl", "daily_pnl",
              "cash_balance", "withdrawable", "available"):
        v = getattr(args, k, None)
        if v is not None:
            updates[k] = v
    holdings = _load_json_array(args.holdings_json, args.holdings_file)
    if holdings is not None:
        updates["holdings"] = holdings
    trades = _load_json_array(args.trades_json, args.trades_file)
    if trades is not None:
        updates["trades"] = trades

    if not updates:
        print('{"error": "no fields to update"}')
        return

    ok = update_log(args.id, updates)
    if not ok and get_log(args.id) is None:
        print(f'{{"error": "log {args.id} not found"}}', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"ok": ok}))


def cmd_delete(args):
    ok = delete_log(args.id)
    print(json.dumps({"ok": ok}))


def cmd_latest(args):
    p = latest_log()
    if not p:
        print("[]", file=sys.stderr)
        sys.exit(1)
    if args.format == "json":
        _to_json(p)
    else:
        _print_table([p])


# ── 辅助 ──


def _load_json_array(json_str: str | None, file_path: str | None) -> list | None:
    """从 --*-json 或 --*-file 加载数组。两者都提供时 json 优先。"""
    if json_str:
        return json.loads(json_str)
    if file_path:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _to_json(obj):
    def _serialize(v):
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, set):
            return list(v)
        return v

    print(json.dumps(obj, ensure_ascii=False, default=_serialize, indent=2))


def _print_table(docs):
    if not docs:
        print("无记录")
        return
    print(f"{'ID':<28} {'日期':<12} {'总资产':<14} {'总市值':<14} {'总盈亏':<12} {'当日盈亏':<12} 资金余额")
    print("-" * 120)
    for d in docs:
        ta = d.get("total_assets", "-")
        mv = d.get("market_value", "-")
        tp = d.get("total_pnl", "-")
        dp = d.get("daily_pnl", "-")
        cb = d.get("cash_balance", "-")
        print(f"{d['_id']:<28} {d['date']:<12} {ta:<14} {mv:<14} {tp:<12} {dp:<12} {cb}")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="投资组合日终日志 CLI")
    sub = parser.add_subparsers(dest="command")

    # add
    p = sub.add_parser("add", help="新建日终日志")
    p.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    p.add_argument("--total-assets", type=float)
    p.add_argument("--market-value", type=float)
    p.add_argument("--total-pnl", type=float)
    p.add_argument("--daily-pnl", type=float)
    p.add_argument("--cash-balance", type=float)
    p.add_argument("--withdrawable", type=float)
    p.add_argument("--available", type=float)
    p.add_argument("--holdings-json", help="持仓 JSON 数组字符串")
    p.add_argument("--holdings-file", help="持仓 JSON 文件路径")
    p.add_argument("--trades-json", help="成交 JSON 数组字符串")
    p.add_argument("--trades-file", help="成交 JSON 文件路径")
    p.set_defaults(func=cmd_add)

    # get
    p = sub.add_parser("get", help="按 _id 查看单条")
    p.add_argument("id")
    p.set_defaults(func=cmd_get)

    # get-by-date
    p = sub.add_parser("get-by-date", help="按日期查看单条")
    p.add_argument("date", help="日期 YYYY-MM-DD")
    p.set_defaults(func=cmd_get_by_date)

    # list
    p = sub.add_parser("list", help="列出日志")
    p.add_argument("--from", dest="date_from", help="起始日期 YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="截止日期 YYYY-MM-DD")
    p.add_argument("--sort", default="-date")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_list)

    # update
    p = sub.add_parser("update", help="更新日志")
    p.add_argument("id")
    p.add_argument("--total-assets", type=float)
    p.add_argument("--market-value", type=float)
    p.add_argument("--total-pnl", type=float)
    p.add_argument("--daily-pnl", type=float)
    p.add_argument("--cash-balance", type=float)
    p.add_argument("--withdrawable", type=float)
    p.add_argument("--available", type=float)
    p.add_argument("--holdings-json", help="持仓 JSON 数组字符串")
    p.add_argument("--holdings-file", help="持仓 JSON 文件路径")
    p.add_argument("--trades-json", help="成交 JSON 数组字符串")
    p.add_argument("--trades-file", help="成交 JSON 文件路径")
    p.set_defaults(func=cmd_update)

    # delete
    p = sub.add_parser("delete", help="删除日志")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)

    # latest
    p = sub.add_parser("latest", help="查看最近一条")
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_latest)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
