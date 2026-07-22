"""MongoDB CRUD for predictions & lesson_types."""

from datetime import datetime, timezone
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

_MONGO_URI = "mongodb://localhost:27017"
_DB_NAME = "vocab"

_client: MongoClient | None = None


def _get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(_MONGO_URI)
    return _client


def get_db() -> Database:
    return _get_client()[_DB_NAME]


def predictions() -> Collection:
    return get_db()["predictions"]


def lesson_types() -> Collection:
    return get_db()["lesson_types"]


# ── Indexes ──


def ensure_indexes():
    predictions().create_index([("result", 1), ("deadline", 1)])
    predictions().create_index([("target", 1), ("created_at", -1)])
    predictions().create_index([("created_at", -1)])
    lesson_types().create_index("name", unique=True)


# ── Predictions CRUD ──


def create_prediction(
    judgment: str,
    target: str,
    confidence: str,
    originator: str = "海宁",
    rationale: str = "",
    deadline: datetime | None = None,
    result: str = "pending",
    review: str = "",
    lesson_type_id: str | None = None,
    lesson: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
    featured: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    doc = {
        "created_at": now,
        "updated_at": now,
        "judgment": judgment,
        "target": target,
        "confidence": confidence,
        "originator": originator,
        "rationale": rationale or "",
        "deadline": deadline,
        "result": result,
        "review": review or "",
        "lesson_type_id": ObjectId(lesson_type_id) if lesson_type_id else None,
        "lesson": lesson or "",
        "tags": tags or [],
        "pinned": pinned,
        "featured": featured,
        "supersedes": None,
        "superseded_by": None,
    }
    ret = predictions().insert_one(doc)
    return str(ret.inserted_id)


def get_prediction(pred_id: str) -> dict | None:
    doc = predictions().find_one({"_id": ObjectId(pred_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
        if doc.get("lesson_type_id"):
            doc["lesson_type_id"] = str(doc["lesson_type_id"])
        if doc.get("supersedes"):
            doc["supersedes"] = str(doc["supersedes"])
        if doc.get("superseded_by"):
            doc["superseded_by"] = str(doc["superseded_by"])
    return doc


def list_predictions(
    result: str | None = None,
    target: str | None = None,
    originator: str | None = None,
    featured: bool | None = None,
    sort: str = "-created_at",
    limit: int = 100,
) -> list[dict]:
    query = {}
    if result:
        query["result"] = result
    if target:
        query["target"] = target
    if originator:
        query["originator"] = originator
    if featured is not None:
        query["featured"] = featured

    sort_dir = -1 if sort.startswith("-") else 1
    sort_field = sort.lstrip("-")

    # 置顶在前，再按时间排序
    sort_spec = [("pinned", -1), (sort_field, sort_dir)]

    docs = list(
        predictions()
        .find(query)
        .sort(sort_spec)
        .limit(limit)
    )
    for d in docs:
        d["_id"] = str(d["_id"])
        if d.get("lesson_type_id"):
            d["lesson_type_id"] = str(d["lesson_type_id"])
    return docs


def update_prediction(pred_id: str, updates: dict) -> bool:
    allowed = {
        "judgment", "target", "confidence", "originator",
        "rationale", "deadline", "result", "review",
        "lesson_type_id", "lesson", "tags", "pinned", "featured",
    }
    to_set = {}
    for k, v in updates.items():
        if k in allowed:
            if k == "lesson_type_id" and v:
                to_set[k] = ObjectId(v)
            elif k == "deadline" and v:
                to_set[k] = v if isinstance(v, datetime) else datetime.fromisoformat(v)
            elif k == "pinned":
                to_set[k] = bool(v)
            else:
                to_set[k] = v
        elif k == "tags" and v is not None:
            to_set[k] = v

    if not to_set:
        return False

    to_set["updated_at"] = datetime.now(timezone.utc)
    ret = predictions().update_one(
        {"_id": ObjectId(pred_id)},
        {"$set": to_set},
    )
    return ret.modified_count > 0


def delete_prediction(pred_id: str) -> bool:
    ret = predictions().delete_one({"_id": ObjectId(pred_id)})
    return ret.deleted_count > 0


def supersede_prediction(old_id: str, new_id: str) -> bool:
    """关旧建新：标记旧预判 amended，指向新预判。"""
    now = datetime.now(timezone.utc)
    predictions().update_one(
        {"_id": ObjectId(old_id)},
        {"$set": {
            "result": "amended",
            "superseded_by": ObjectId(new_id),
            "updated_at": now,
        }},
    )
    predictions().update_one(
        {"_id": ObjectId(new_id)},
        {"$set": {
            "supersedes": ObjectId(old_id),
            "updated_at": now,
        }},
    )
    return True


# ── Lesson types CRUD ──


def list_lesson_types() -> list[dict]:
    docs = list(lesson_types().find())
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def add_lesson_type(name: str, description: str = "") -> str:
    doc = {"name": name, "description": description or ""}
    ret = lesson_types().insert_one(doc)
    return str(ret.inserted_id)


def delete_lesson_type(lt_id: str) -> bool:
    ret = lesson_types().delete_one({"_id": ObjectId(lt_id)})
    return ret.deleted_count > 0


def seed_lesson_types():
    """插入初始种子数据（幂等）。"""
    seeds = [
        ("纪律执行", "违反了自己定的规则"),
        ("分析框架", "推理框架/方式有问题"),
        ("认知偏差", "理性市场假设、确认偏差等心理效应"),
        ("执行流程", "流程没走完就动手（快一小步）"),
        ("仓位管理", "仓位/资金规划问题"),
        ("判断方法", "技术性的判断方法缺陷"),
    ]
    for name, desc in seeds:
        if not lesson_types().find_one({"name": name}):
            lesson_types().insert_one({"name": name, "description": desc})


# ── Init ──

ensure_indexes()
seed_lesson_types()
