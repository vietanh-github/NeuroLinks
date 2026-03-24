"""Firebase Admin SDK client for NeuroLinks bot.

Scalability design:
- Pagination uses Firestore .offset() + .limit() + count() aggregation — no full scans.
- Stats are maintained in a dedicated `stats/links` document updated atomically on
  every add/delete, so get_stats() is a single document read (O(1)).
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import aggregation

_db = None

def get_db():
    global _db
    if _db is None:
        _here    = os.path.dirname(os.path.abspath(__file__))
        _root    = os.path.dirname(_here)          # NeuroLinks/
        default  = os.path.join(_root, "neurolinks-4b8d9-firebase-adminsdk-fbsvc-180872d1e2.json")
        sa_path  = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", default)
        if not os.path.isabs(sa_path):
            sa_path = os.path.join(_root, sa_path)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(sa_path))
        _db = firestore.client()
    return _db


# ── Settings ──────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "categories":      ["AI", "ML", "Tools", "News", "Other"],
    "allowed_user_ids": [],
    "sub_admin_ids":   [],
}

def get_settings() -> dict:
    ref = get_db().collection("settings").document("main")
    doc = ref.get()
    if doc.exists:
        data = DEFAULT_SETTINGS.copy()
        data.update(doc.to_dict())
        return data
    ref.set(DEFAULT_SETTINGS)
    return DEFAULT_SETTINGS.copy()

def save_settings(data: dict) -> None:
    get_db().collection("settings").document("main").set(data, merge=True)

# ── Categories ────────────────────────────────────────────────────────────────

def get_categories() -> list[str]:
    return get_settings().get("categories", [])

def add_category(name: str) -> bool:
    cats = get_categories()
    if name in cats: return False
    cats.append(name); save_settings({"categories": cats}); return True

def remove_category(name: str) -> bool:
    cats = get_categories()
    if name not in cats: return False
    cats.remove(name); save_settings({"categories": cats}); return True

# ── Allowed users ─────────────────────────────────────────────────────────────

def get_allowed_users() -> list[int]:
    return get_settings().get("allowed_user_ids", [])

def add_allowed_user(user_id: int) -> bool:
    users = get_allowed_users()
    if user_id in users: return False
    users.append(user_id); save_settings({"allowed_user_ids": users}); return True

def remove_allowed_user(user_id: int) -> bool:
    users = get_allowed_users()
    if user_id not in users: return False
    users.remove(user_id); save_settings({"allowed_user_ids": users}); return True

# ── Sub-admins ────────────────────────────────────────────────────────────────

def get_sub_admins() -> list[int]:
    return get_settings().get("sub_admin_ids", [])

def add_sub_admin(user_id: int) -> bool:
    subs = get_sub_admins()
    if user_id in subs: return False
    subs.append(user_id); save_settings({"sub_admin_ids": subs}); return True

def remove_sub_admin(user_id: int) -> bool:
    subs = get_sub_admins()
    if user_id not in subs: return False
    subs.remove(user_id); save_settings({"sub_admin_ids": subs}); return True

def is_sub_admin(user_id: int, admin_id: int) -> bool:
    return user_id == admin_id or user_id in get_sub_admins()

def is_user_allowed(user_id: int, admin_id: int) -> bool:
    if user_id == admin_id: return True
    s = get_settings()
    return user_id in s.get("sub_admin_ids", []) or user_id in s.get("allowed_user_ids", [])


# ── Stats document (maintained atomically) ────────────────────────────────────

def _stats_ref():
    return get_db().collection("stats").document("links")

def _increment_stats(category: str, delta: int = 1):
    """Atomically increment total and per-category counter."""
    ref = _stats_ref()
    ref.set({
        "total": firestore.Increment(delta),
        "by_category": {category: firestore.Increment(delta)},
    }, merge=True)

def get_stats() -> dict:
    """O(1) read — stats maintained by add/delete operations."""
    doc = _stats_ref().get()
    if not doc.exists:
        # First-time: rebuild from collection (one-time cost)
        return _rebuild_stats()
    data = doc.to_dict()
    return {
        "total":       data.get("total", 0),
        "by_category": data.get("by_category", {}),
    }

def _rebuild_stats() -> dict:
    """Rebuild stats document by scanning all links (used only once if doc missing)."""
    docs = list(get_db().collection("links").stream())
    cats: dict[str, int] = {}
    for d in docs:
        cat = d.to_dict().get("category", "Unknown")
        cats[cat] = cats.get(cat, 0) + 1
    total = len(docs)
    _stats_ref().set({"total": total, "by_category": cats})
    return {"total": total, "by_category": cats}


# ── Links CRUD ────────────────────────────────────────────────────────────────

def add_link(url: str, category: str, user_id: int, username: str) -> str:
    doc_ref = get_db().collection("links").document()
    doc_ref.set({
        "url":        url,
        "category":   category,
        "user_id":    str(user_id),
        "username":   username or f"user_{user_id}",
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    _increment_stats(category, +1)
    return doc_ref.id

def find_link_by_url(url: str) -> dict | None:
    """Return existing link dict (with 'id') if URL already saved, else None."""
    docs = list(
        get_db().collection("links")
        .where("url", "==", url)
        .limit(1)
        .stream()
    )
    if docs:
        return {"id": docs[0].id, **docs[0].to_dict()}
    return None

def get_links(limit: int = 10, category_filter: str | None = None) -> list[dict]:
    q = (get_db().collection("links")
         .order_by("created_at", direction=firestore.Query.DESCENDING)
         .limit(limit))
    if category_filter:
        q = q.where("category", "==", category_filter)
    return [{"id": d.id, **d.to_dict()} for d in q.stream()]

def get_links_paginated(page: int, per_page: int = 5) -> tuple[list[dict], int]:
    """
    Efficient pagination using Firestore .offset() + .limit().
    Total count comes from the stats document (O(1)).
    Note: .offset() is supported by the Admin SDK and reads only
    (page * per_page + per_page) documents server-side.
    """
    total = get_stats()["total"]
    q = (get_db().collection("links")
         .order_by("created_at", direction=firestore.Query.DESCENDING)
         .offset(page * per_page)
         .limit(per_page))
    docs = [{"id": d.id, **d.to_dict()} for d in q.stream()]
    return docs, total

def delete_link(doc_id: str) -> bool:
    ref = get_db().collection("links").document(doc_id)
    snap = ref.get()
    if not snap.exists:
        return False
    category = snap.to_dict().get("category", "Unknown")
    ref.delete()
    _increment_stats(category, -1)
    return True

def update_link_category(doc_id: str, new_category: str) -> bool:
    ref = get_db().collection("links").document(doc_id)
    snap = ref.get()
    if not snap.exists:
        return False
    old_category = snap.to_dict().get("category", "Unknown")
    ref.update({"category": new_category})
    # Update counters: -1 old, +1 new
    _stats_ref().set({
        "by_category": {
            old_category: firestore.Increment(-1),
            new_category: firestore.Increment(+1),
        }
    }, merge=True)
    return True
