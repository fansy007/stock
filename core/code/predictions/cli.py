#!/usr/bin/env python3
"""预判系统 CLI — skill & webapp 均通过此入口操作数据。"""

import argparse
import json
import re
import sys
from datetime import datetime

from core.code.predictions.db import (
    create_prediction,
    get_prediction,
    list_predictions,
    update_prediction,
    delete_prediction,
    supersede_prediction,
    list_lesson_types,
    add_lesson_type,
    delete_lesson_type,
)


def cmd_add(args):
    pid = create_prediction(
        judgment=args.judgment,
        target=args.target,
        confidence=args.confidence,
        originator=args.originator,
        rationale=args.rationale or "",
        deadline=datetime.fromisoformat(args.deadline) if args.deadline else None,
        result=args.result,
        review=args.review or "",
        lesson_type_id=args.lesson_type_id,
        lesson=args.lesson or "",
        tags=args.tags.split(",") if args.tags else [],
        pinned=args.pinned,
        featured=args.featured,
    )
    print(pid)


def cmd_get(args):
    p = get_prediction(args.id)
    if not p:
        print("[]", file=sys.stderr)
        sys.exit(1)
    _to_json(p)


def cmd_list(args):
    docs = list_predictions(
        result=args.result,
        target=args.target,
        originator=args.originator,
        featured=args.featured,
        sort=args.sort,
        limit=args.limit,
    )
    if args.format == "json":
        _to_json(docs)
    else:
        _print_table(docs)


def cmd_update(args):
    updates = {}
    for k in ("judgment", "target", "confidence", "originator",
              "rationale", "result", "review", "lesson_type_id", "lesson"):
        v = getattr(args, k, None)
        if v is not None:
            updates[k] = v
    if args.pinned is not None:
        updates["pinned"] = args.pinned
    if args.featured is not None:
        updates["featured"] = args.featured
    if args.tags:
        updates["tags"] = args.tags.split(",")
    if args.deadline:
        updates["deadline"] = datetime.fromisoformat(args.deadline)

    if not updates:
        print("{\"error\": \"no fields to update\"}")
        return

    ok = update_prediction(args.id, updates)
    if not ok and args.result and get_prediction(args.id) is None:
        print(f'{{"error": "prediction {args.id} not found"}}', file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"ok": ok}))


def cmd_delete(args):
    ok = delete_prediction(args.id)
    print(json.dumps({"ok": ok}))


def cmd_supersede(args):
    supersede_prediction(args.old_id, args.new_id)
    print(json.dumps({"ok": True}))


def cmd_lesson_types(args):
    lts = list_lesson_types()
    if args.format == "json":
        _to_json(lts)
    else:
        print(f"{'ID':<28} {'名称':<12} 说明")
        print("-" * 60)
        for lt in lts:
            print(f"{lt['_id']:<28} {lt['name']:<12} {lt['description']}")


def cmd_add_lesson_type(args):
    lt_id = add_lesson_type(args.name, args.description or "")
    print(lt_id)


def cmd_delete_lesson_type(args):
    ok = delete_lesson_type(args.id)
    print(json.dumps({"ok": ok}))


def cmd_import_obsidian(args):
    """从 Obsidian markdown 导入预判记录。"""
    with open(args.file, "r", encoding="utf-8") as f:
        content = f.read()

    # 按 ### 分割每条记录
    blocks = re.split(r"\n### ", content)
    imported = 0
    skipped = 0

    for block in blocks:
        if not block.strip():
            continue

        # 如果被 ### 分割时去掉了前缀，补回来
        if not block.startswith("###") and not block.startswith("2026"):
            block = "### " + block

        pred = _parse_obsidian_block(block)
        if pred is None:
            skipped += 1
            continue

        # 检查是否已导入（按 judgment 去重）
        existing = list_predictions(limit=10)
        dup = any(e["judgment"].strip()[:40] == pred["judgment"].strip()[:40] for e in existing)
        if dup and not args.force:
            skipped += 1
            continue

        pid = create_prediction(**pred)
        print(f"  ✓ {pred['target'][:20]:<20} {pred['result']:<8} → {pid}", file=sys.stderr)
        imported += 1

    result = {"imported": imported, "skipped": skipped}
    print(json.dumps(result))


_RESULT_MAP = {
    "⏳": "pending",
    "✅": "correct",
    "❌": "wrong",
    "△": "amended",
}

_CONFIDENCE_PATTERN = re.compile(r"(低|中偏低|中|中偏高|高|信念)")


def _parse_obsidian_block(block: str) -> dict | None:
    """解析一条 Obsidian 预判记录块，返回 create_prediction 参数 dict。"""
    if not block.strip():
        return None

    lines = block.strip().split("\n")

    # 标题行: ### 2026-06-07 美伊两周内和平协议
    title_line = lines[0].lstrip("# ")
    title_parts = title_line.strip().split(maxsplit=1)

    if len(title_parts) < 2:
        return None

    date_str = title_parts[0]
    title = title_parts[1]

    # 判断发起人
    originator = "海宁"
    title_lower = title.lower()
    if "爱因斯坦" in title or "ai" in title_lower:
        originator = "爱因斯坦"

    # 提取 target（标题第一个词通常是标的）
    target = title.split()[0] if title.split() else title

    # 解析字段
    fields = {
        "发起人": None, "判断": None, "依据": None,
        "置信度": None, "验证条件": None, "结果": None, "复盘": None,
    }
    current_key = None
    current_value = []

    def _save_field():
        nonlocal current_key, current_value
        if current_key and current_value:
            text = "\n".join(current_value).strip()
            # 去掉列表项前缀
            text = re.sub(r"\n\s*[-\d]+\.\s*", "\n", text)
            text = text.strip(" -")
            if current_key in fields:
                fields[current_key] = text

    for line in lines[1:]:
        m = re.match(r"\*\*([^:]+):\*\*\s*(.*)", line)
        if m:
            _save_field()
            current_key = m.group(1)
            current_value = [m.group(2).strip()]
        elif current_key and line.strip():
            current_value.append(line.strip())

    _save_field()

    judgment = fields["判断"] or title
    rationale = fields["依据"] or ""

    # 置信度
    raw_conf = fields["置信度"] or ""
    conf_match = _CONFIDENCE_PATTERN.search(raw_conf)
    confidence = conf_match.group(1) if conf_match else "中"

    # 结果
    raw_result = fields["结果"] or ""
    result = "pending"
    for sym, r in _RESULT_MAP.items():
        if sym in raw_result:
            result = r
            break

    # deadline 从验证条件或结果里提取
    deadline = None
    raw_condition = fields["验证条件"] or ""
    raw_result_text = fields["结果"] or ""

    # 从结果里提取截止日期：⏳ 待验证（截止：2026-06-21）
    deadline_match = re.search(r"截止[：:]\s*(\d{4}-\d{2}-\d{2})", raw_result_text)
    if not deadline_match:
        deadline_match = re.search(r"(\d{4}-\d{2}-\d{2})前", raw_condition)
    if deadline_match:
        try:
            deadline = datetime.fromisoformat(deadline_match.group(1))
        except ValueError:
            pass

    # 复盘
    review = fields["复盘"] or ""

    # 发起人
    originator = fields.get("发起人") or originator
    # 去掉括号内容
    originator = re.sub(r"[（(].*?[）)]", "", originator).strip() or "海宁"

    return {
        "judgment": judgment,
        "target": target,
        "confidence": confidence,
        "originator": originator,
        "rationale": rationale,
        "deadline": deadline,
        "result": result,
        "review": review,
    }


# ── 输出格式化 ──


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
    print(f"{'ID':<28} {'标的':<10} {'置信度':<8} {'结果':<10} {'截止':<14} 判断")
    print("-" * 120)
    for d in docs:
        dl = d.get("deadline")
        dl_str = dl.isoformat()[:10] if dl else "-"
        jdg = d["judgment"][:50] + ("…" if len(d["judgment"]) > 50 else "")
        print(f"{d['_id']:<28} {d['target']:<10} {d['confidence']:<8} {d['result']:<10} {dl_str:<14} {jdg}")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="预判系统 CLI")
    sub = parser.add_subparsers(dest="command")

    # add
    p = sub.add_parser("add", help="新建预判")
    p.add_argument("--judgment", required=True)
    p.add_argument("--target", required=True, help='主题概述，如"菲利华中线走势"、"黄金短线走势"')
    p.add_argument("--confidence", required=True)
    p.add_argument("--originator", default="海宁")
    p.add_argument("--rationale")
    p.add_argument("--deadline")
    p.add_argument("--result", default="pending")
    p.add_argument("--review")
    p.add_argument("--lesson-type-id")
    p.add_argument("--lesson")
    p.add_argument("--tags")
    p.add_argument("--pinned", action="store_true", default=False)
    p.add_argument("--featured", action="store_true", default=False)
    p.set_defaults(func=cmd_add)

    # get
    p = sub.add_parser("get", help="查看单条")
    p.add_argument("id")
    p.set_defaults(func=cmd_get)

    # list
    p = sub.add_parser("list", help="列出预判")
    p.add_argument("--result")
    p.add_argument("--target")
    p.add_argument("--originator")
    p.add_argument("--featured", action="store_true", default=None)
    p.add_argument("--sort", default="-created_at")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_list)

    # update
    p = sub.add_parser("update", help="更新预判")
    p.add_argument("id")
    p.add_argument("--judgment")
    p.add_argument("--target")
    p.add_argument("--confidence")
    p.add_argument("--originator")
    p.add_argument("--rationale")
    p.add_argument("--deadline")
    p.add_argument("--result")
    p.add_argument("--review")
    p.add_argument("--lesson-type-id")
    p.add_argument("--lesson")
    p.add_argument("--tags")
    p.add_argument("--pinned", action="store_true", default=None)
    p.add_argument("--no-pinned", action="store_false", dest="pinned", default=None)
    p.add_argument("--featured", action="store_true", default=None)
    p.add_argument("--no-featured", action="store_false", dest="featured", default=None)
    p.set_defaults(func=cmd_update)

    # delete
    p = sub.add_parser("delete", help="删除预判")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)

    # supersede
    p = sub.add_parser("supersede", help="关旧建新")
    p.add_argument("old_id")
    p.add_argument("new_id")
    p.set_defaults(func=cmd_supersede)

    # lesson-types
    p = sub.add_parser("lesson-types", help="列出教训类型")
    p.add_argument("--format", choices=["table", "json"], default="table")
    p.set_defaults(func=cmd_lesson_types)

    # add-lesson-type
    p = sub.add_parser("add-lesson-type", help="新增教训类型")
    p.add_argument("--name", required=True)
    p.add_argument("--description")
    p.set_defaults(func=cmd_add_lesson_type)

    # delete-lesson-type
    p = sub.add_parser("delete-lesson-type", help="删除教训类型")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete_lesson_type)

    # import-obsidian
    p = sub.add_parser("import-obsidian", help="从 Obsidian markdown 导入")
    p.add_argument("--file", required=True)
    p.add_argument("--force", action="store_true", help="强制导入已存在的预判")
    p.set_defaults(func=cmd_import_obsidian)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
