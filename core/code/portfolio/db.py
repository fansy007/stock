"""MongoDB CRUD for portfolio daily logs."""

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


def portfolio_logs() -> Collection:
    return get_db()["portfolio_logs"]


# ── Indexes ──


def ensure_indexes():
    portfolio_logs().create_index("date", unique=True)
    portfolio_logs().create_index([("created_at", -1)])


# ── CRUD ──


def create_log(
    date: str,
    total_assets: float | None = None,
    market_value: float | None = None,
    total_pnl: float | None = None,
    daily_pnl: float | None = None,
    cash_balance: float | None = None,
    withdrawable: float | None = None,
    available: float | None = None,
    holdings: list[dict] | None = None,
    trades: list[dict] | None = None,
) -> str:
    """新建日终日志。date 已存在则更新（upsert on date）。"""
    now = datetime.now(timezone.utc)
    doc = {
        "date": date,
        "total_assets": total_assets,
        "market_value": market_value,
        "total_pnl": total_pnl,
        "daily_pnl": daily_pnl,
        "cash_balance": cash_balance,
        "withdrawable": withdrawable,
        "available": available,
        "holdings": holdings or [],
        "trades": trades or [],
        "created_at": now,
        "updated_at": now,
    }
    ret = portfolio_logs().update_one(
        {"date": date},
        {"$set": doc},
        upsert=True,
    )
    # Return the inserted or matched doc's _id
    existing = portfolio_logs().find_one({"date": date})
    return str(existing["_id"]) if existing else ""


def get_log(log_id: str) -> dict | None:
    doc = portfolio_logs().find_one({"_id": ObjectId(log_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def get_log_by_date(date: str) -> dict | None:
    doc = portfolio_logs().find_one({"date": date})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


def list_logs(
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "-date",
    limit: int = 100,
) -> list[dict]:
    query = {}
    if date_from or date_to:
        q = {}
        if date_from:
            q["$gte"] = date_from
        if date_to:
            q["$lte"] = date_to
        query["date"] = q

    sort_dir = -1 if sort.startswith("-") else 1
    sort_field = sort.lstrip("-")

    docs = list(
        portfolio_logs()
        .find(query)
        .sort(sort_field, sort_dir)
        .limit(limit)
    )
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


def update_log(log_id: str, updates: dict) -> bool:
    allowed = {
        "total_assets", "market_value", "total_pnl", "daily_pnl",
        "cash_balance", "withdrawable", "available",
        "holdings", "trades",
    }
    to_set = {}
    for k, v in updates.items():
        if k in allowed:
            to_set[k] = v

    if not to_set:
        return False

    to_set["updated_at"] = datetime.now(timezone.utc)
    ret = portfolio_logs().update_one(
        {"_id": ObjectId(log_id)},
        {"$set": to_set},
    )
    return ret.modified_count > 0


def delete_log(log_id: str) -> bool:
    ret = portfolio_logs().delete_one({"_id": ObjectId(log_id)})
    return ret.deleted_count > 0


def latest_log() -> dict | None:
    docs = list(portfolio_logs().find().sort("date", -1).limit(1))
    if docs:
        docs[0]["_id"] = str(docs[0]["_id"])
        return docs[0]
    return None


# ── Init ──

ensure_indexes()
