#!/usr/bin/env python3
"""自选股 CLI — skill & webapp 均通过此入口操作数据。"""

import argparse
import json
import sys
from datetime import datetime

from core.code.candidates.db import (
    create_candidate,
    get_candidate,
    get_candidate_by_code,
    list_candidates,
    update_candidate,
    delete_candidate,
    list_tags,
    add_tag,
    delete_tag,
)


def cmd_add(args):
    existing = get_candidate_by_code(args.code)
    if existing:
        print(f'{{"error": "stock {args.code} already exists as candidate {existing["_id"]}"}}',
              file=sys.stderr)
        sys.exit(1)
    cand_id = create_candidate(
        stock_code=args.code,
        name=args.name,
        note=args.note or "",
        score=args.score or 128,
        tags=args.tags.split(",") if args.tags else [],
        price_when_added=args.price,
        concept=args.concept or "",
    )
    print(cand_id)


def cmd_get(args):
    c = get_candidate(args.id)
    if not c:
        print("null", file=sys.stderr)
        sys.exit(1)
    _to_json(c)


def cmd_list(args):
    docs = list_candidates(
        tag=args.tag,
        limit=args.limit,
    )
    if args.format == "json":
        _to_json(docs)
    else:
        _print_table(docs)


def cmd_update(args):
    updates = {}
    for k in ("note", "score"):
        v = getattr(args, k, None)
        if v is not None:
            updates[k] = v
    if args.tags:
        updates["tags"] = args.tags.split(",")

    if not updates:
        print('{"error": "no fields to update"}')
        return

    ok = update_candidate(args.id, updates)
    if not ok:
        print(f'{{"error": "candidate {args.id} not found"}}', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"ok": ok}))


def cmd_delete(args):
    ok = delete_candidate(args.id)
    print(json.dumps({"ok": ok}))


# ── Tags ──


def cmd_list_tags(args):
    docs = list_tags()
    if args.format == "json":
        _to_json(docs)
    else:
        print(f"{'ID':<28} {'名称':<12}")
        print("-" * 42)
        for t in docs:
            print(f"{t['_id']:<28} {t['name']:<12}")


def cmd_add_tag(args):
    tag_id = add_tag(args.name)
    print(tag_id)


def cmd_delete_tag(args):
    ok = delete_tag(args.id)
    print(json.dumps({"ok": ok}))


# ── Output ──


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
    print(f"{'ID':<28} {'代码':<12} {'名称':<10} {'评分':<6} 备注")
    print("-" * 90)
    for d in docs:
        note = (d.get("note") or "")[:40] + ("…" if len(d.get("note") or "") > 40 else "")
        score = d.get("score", "-")
        print(f"{d['_id']:<28} {d['stock_code']:<12} {d['name']:<10} {score:<6} {note}")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="自选股/候选股 CLI")
    sub = parser.add_subparsers(dest="command")

    # add
    p = sub.add_parser("add", help="添加候选股")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--score", type=int, default=128)
    p.add_argument("--note")
    p.add_argument("--tags")
    p.add_argument("--price", type=float)
    p.add_argument("--concept", help="所属概念板块")
    p.set_defaults(func=cmd_add)

    # get
    p = sub.add_parser("get", help="查看单条")
    p.add_argument("id")
    p.set_defaults(func=cmd_get)

    # list
    p = sub.add_parser("list", help="列出候选股")
    p.add_argument("--tag")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_list)

    # update
    p = sub.add_parser("update", help="更新候选股")
    p.add_argument("id")
    p.add_argument("--note")
    p.add_argument("--score", type=int)
    p.add_argument("--tags")
    p.set_defaults(func=cmd_update)

    # delete
    p = sub.add_parser("delete", help="删除候选股")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)

    # tag commands
    p = sub.add_parser("add-tag", help="添加标签类型")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add_tag)

    p = sub.add_parser("list-tags", help="列出标签类型")
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_list_tags)

    p = sub.add_parser("delete-tag", help="删除标签类型")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete_tag)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
