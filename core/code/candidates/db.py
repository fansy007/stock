"""MongoDB CRUD for candidates & candidate_tags."""

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


def candidates() -> Collection:
    return get_db()["candidates"]


def candidate_tags() -> Collection:
    return get_db()["candidate_tags"]


# ── Indexes ──


def ensure_indexes():
    candidates().create_index([("created_at", -1)])
    candidates().create_index("stock_code", unique=True)
    candidate_tags().create_index("name", unique=True)


# ── Candidate Tags CRUD ──


def list_tags() -> list[dict]:
    docs = list(candidate_tags().find())
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def add_tag(name: str) -> str:
    doc = {"name": name, "created_at": datetime.now(timezone.utc)}
    ret = candidate_tags().insert_one(doc)
    return str(ret.inserted_id)


def delete_tag(tag_id: str) -> bool:
    ret = candidate_tags().delete_one({"_id": ObjectId(tag_id)})
    return ret.deleted_count > 0


def seed_tags():
    seeds = ["观察中", "预备池", "准备买入", "已买入", "待研究"]
    for name in seeds:
        if not candidate_tags().find_one({"name": name}):
            candidate_tags().insert_one({"name": name, "created_at": datetime.now(timezone.utc)})


# ── Candidates CRUD ──


def create_candidate(
    stock_code: str,
    name: str,
    note: str = "",
    score: int = 128,
    tags: list[str] | None = None,
    price_when_added: float | None = None,
    concept: str = "",
) -> str:
    now = datetime.now(timezone.utc)
    doc = {
        "stock_code": stock_code,
        "name": name,
        "note": note or "",
        "score": score,
        "tags": tags or [],
        "concept": concept or "",
        "price_when_added": price_when_added,
        "created_at": now,
        "updated_at": now,
    }
    ret = candidates().insert_one(doc)
    return str(ret.inserted_id)


def get_candidate(cand_id: str) -> dict | None:
    doc = candidates().find_one({"_id": ObjectId(cand_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_candidate_by_code(code: str) -> dict | None:
    doc = candidates().find_one({"stock_code": code})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def list_candidates(
    tag: str | None = None,
    sort: str = "-created_at",
    limit: int = 100,
) -> list[dict]:
    query = {}
    if tag:
        query["tags"] = tag

    sort_dir = -1 if sort.startswith("-") else 1
    sort_field = sort.lstrip("-")

    docs = list(
        candidates()
        .find(query)
        .sort(sort_field, sort_dir)
        .limit(limit)
    )
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def update_candidate(cand_id: str, updates: dict) -> bool:
    allowed = {"note", "score", "tags"}
    to_set = {}
    for k, v in updates.items():
        if k in allowed:
            to_set[k] = v

    if not to_set:
        return False

    to_set["updated_at"] = datetime.now(timezone.utc)
    ret = candidates().update_one(
        {"_id": ObjectId(cand_id)},
        {"$set": to_set},
    )
    return ret.modified_count > 0


def delete_candidate(cand_id: str) -> bool:
    ret = candidates().delete_one({"_id": ObjectId(cand_id)})
    return ret.deleted_count > 0


# ── Init ──

ensure_indexes()
seed_tags()
