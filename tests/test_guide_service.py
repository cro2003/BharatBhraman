"""Guide marketplace logic: pricing, validation, and review aggregation."""
import copy

import pytest
from bson.objectid import ObjectId

from app.services.guide_service import GuideService


class FakeCollection:
    """Minimal in-memory stand-in for a pymongo collection."""
    def __init__(self, docs=None):
        self.docs = {d["_id"]: d for d in (docs or [])}
        self.inserted = []

    def find_one(self, query):
        # pymongo returns a fresh document each call; copy so a later $push to the
        # stored doc doesn't retroactively mutate a snapshot the caller is holding.
        doc = self.docs.get(query.get("_id"))
        return copy.deepcopy(doc) if doc is not None else None

    def insert_one(self, doc):
        oid = ObjectId()
        doc = {**doc}
        self.inserted.append(doc)
        class R:  # noqa
            inserted_id = oid
        return R()

    def update_one(self, query, update):
        doc = self.docs.get(query.get("_id"))
        if not doc:
            return
        if "$push" in update:
            for k, v in update["$push"].items():
                doc.setdefault(k, []).append(v)
        if "$set" in update:
            doc.update(update["$set"])


@pytest.fixture
def svc(monkeypatch):
    s = GuideService.__new__(GuideService)
    s.guides = FakeCollection()
    s.bookings = FakeCollection()
    s.platform_fee = 0.25
    return s


# ----------------------------------------------------------------- pricing

def test_quote_applies_platform_fee(svc):
    q = svc.quote_booking(hourly_rate=1000, hours=2)
    assert q["base_price"] == 2000.0
    assert q["platform_fee"] == 500.0      # 25%
    assert q["total_price"] == 2500.0


def test_quote_respects_env_fee(svc):
    svc.platform_fee = 0.10
    q = svc.quote_booking(500, 4)
    assert q["base_price"] == 2000.0
    assert q["platform_fee"] == 200.0
    assert q["total_price"] == 2200.0


# ----------------------------------------------------------------- booking

def test_book_unknown_guide_returns_none(svc):
    assert svc.book_guide("user1", str(ObjectId()), "2026-07-01", 2) is None


def test_book_malformed_id_returns_none(svc):
    assert svc.book_guide("user1", "not-an-objectid", "2026-07-01", 2) is None


def test_book_known_guide_records_breakdown(svc):
    gid = ObjectId()
    svc.guides.docs[gid] = {"_id": gid, "name": "Asha", "hourly_rate": 800}
    booking = svc.book_guide("user1", str(gid), "2026-07-01", 3)
    assert booking["guide_name"] == "Asha"
    assert booking["base_price"] == 2400.0
    assert booking["platform_fee"] == 600.0
    assert booking["total_price"] == 3000.0
    assert booking["status"] == "pending"
    assert booking["hours"] == 3.0


# ----------------------------------------------------------------- reviews

def test_review_unknown_guide_returns_false(svc):
    assert svc.add_review(str(ObjectId()), "Bob", 5, "great") is False


def test_first_review_sets_rating_and_count(svc):
    gid = ObjectId()
    svc.guides.docs[gid] = {"_id": gid, "name": "Asha", "reviews": []}
    assert svc.add_review(str(gid), "Bob", 4, "good") is True
    doc = svc.guides.docs[gid]
    assert doc["rating"] == 4.0
    assert doc["review_count"] == 1
    assert len(doc["reviews"]) == 1


def test_review_recomputes_average(svc):
    gid = ObjectId()
    svc.guides.docs[gid] = {"_id": gid, "name": "Asha",
                            "reviews": [{"rating": 5.0}, {"rating": 3.0}]}
    svc.add_review(str(gid), "Bob", 4, "ok")
    doc = svc.guides.docs[gid]
    assert doc["rating"] == 4.0      # (5+3+4)/3
    assert doc["review_count"] == 3


def test_register_has_no_fake_rating_or_verified(svc):
    gid = svc.register_guide({"name": "Asha", "email": "a@b.com"})
    doc = next(d for d in svc.guides.inserted if d["name"] == "Asha")
    assert doc["rating"] is None
    assert doc["review_count"] == 0
    assert "is_verified" not in doc
