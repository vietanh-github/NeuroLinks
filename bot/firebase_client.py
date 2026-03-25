"""Firebase Admin SDK client for NeuroLinks bot.

Scalability design:
- Settings are cached in-process for 60 s (TTL) to avoid a Firestore read on
  every incoming message.  Writes invalidate the cache immediately.
- Stats are maintained in a dedicated `stats/links` document updated atomically
  on every add/delete, so get_stats() is O(1).
- Pagination uses Firestore .offset() + .limit() — no full scans.
- AI-tag vocabulary is cached for 120 s to avoid a full collection scan on
  every link submission.
"""

import os
import time
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


# ── Settings (with TTL cache) ─────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "categories":      ["AI", "ML", "Tools", "News", "Other"],
    "allowed_user_ids": [],
    "sub_admin_ids":   [],
}

_settings_cache: dict | None = None
_settings_cache_ts: float = 0.0
_SETTINGS_TTL = 60.0  # seconds

# AI tags cache — avoids full collection scan on every link save
_ai_tags_cache: list[str] | None = None
_ai_tags_cache_ts: float = 0.0
_AI_TAGS_TTL = 120.0  # seconds


def _settings_cache_valid() -> bool:
    return _settings_cache is not None and (time.monotonic() - _settings_cache_ts) < _SETTINGS_TTL


def invalidate_settings_cache() -> None:
    """Force the next get_settings() call to re-read from Firestore."""
    global _settings_cache, _settings_cache_ts
    _settings_cache = None
    _settings_cache_ts = 0.0


def get_settings() -> dict:
    global _settings_cache, _settings_cache_ts
    if _settings_cache_valid():
        return _settings_cache  # type: ignore[return-value]
    ref = get_db().collection("settings").document("main")
    doc = ref.get()
    if doc.exists:
        data = DEFAULT_SETTINGS.copy()
        data.update(doc.to_dict())
    else:
        ref.set(DEFAULT_SETTINGS)
        data = DEFAULT_SETTINGS.copy()
    _settings_cache = data
    _settings_cache_ts = time.monotonic()
    return data


def save_settings(data: dict) -> None:
    get_db().collection("settings").document("main").set(data, merge=True)
    invalidate_settings_cache()  # stale immediately after write


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
    s = get_settings()  # O(1) from cache after first call
    return user_id in s.get("sub_admin_ids", []) or user_id in s.get("allowed_user_ids", [])


# ── Stats document (maintained atomically) ────────────────────────────────────

def _stats_ref():
    return get_db().collection("stats").document("links")


def _increment_stats(category: str, delta: int = 1):
    """Atomically increment total and per-category counter."""
    ref = _stats_ref()
    update: dict = {"total": firestore.Increment(delta)}
    if category:  # skip empty/missing category — AI tags replaced categories
        update["by_category"] = {category: firestore.Increment(delta)}
    ref.set(update, merge=True)

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


# ── User activity tracking ─────────────────────────────────────────────────────

def track_user_activity(user_id: int, username: str, link_delta: int = 0) -> None:
    """Upsert a user document and optionally increment their link_count.

    Called on every bot interaction (start, link sent, etc.).
    Stored in the 'users' collection keyed by str(user_id).
    """
    ref = get_db().collection("users").document(str(user_id))
    update: dict = {
        "user_id":  user_id,
        "username": username,
        "last_seen": firestore.SERVER_TIMESTAMP,
    }
    if link_delta:
        update["link_count"] = firestore.Increment(link_delta)
    ref.set(update, merge=True)


def get_all_users_with_stats() -> list[dict]:
    """Return all tracked users sorted by link_count desc.

    Each dict has: user_id, username, link_count, last_seen.
    """
    docs = list(get_db().collection("users").stream())
    users = []
    for d in docs:
        data = d.to_dict()
        users.append({
            "user_id":    data.get("user_id", 0),
            "username":   data.get("username", "—"),
            "link_count": data.get("link_count", 0),
            "last_seen":  data.get("last_seen"),
        })
    users.sort(key=lambda u: u["link_count"], reverse=True)
    return users


def get_notify_pref(user_id: int) -> bool:
    """Return True if the user wants a follow-up notification when their link is processed.
    Defaults to True if not set.
    """
    ref = get_db().collection("users").document(str(user_id))
    doc = ref.get()
    if doc.exists:
        return doc.to_dict().get("notify_done", True)
    return True


def set_notify_pref(user_id: int, enabled: bool) -> None:
    """Persist the notify_done preference for a user."""
    get_db().collection("users").document(str(user_id)).set(
        {"notify_done": enabled}, merge=True
    )


# ── Links CRUD ────────────────────────────────────────────────────────────────

def add_link(url: str, category: str, user_id: int, username: str,
             title: str = "", description: str = "", og_image: str = "") -> str:
    doc_ref = get_db().collection("links").document()
    doc_ref.set({
        "url":         url,
        "category":    category,
        "user_id":     str(user_id),
        "username":    username or f"user_{user_id}",
        "created_at":  firestore.SERVER_TIMESTAMP,
        "title":       title,
        "description": description,
        "og_image":    og_image,
    })
    _increment_stats(category, +1)
    return doc_ref.id

def update_link_metadata(doc_id: str, title: str, description: str, og_image: str) -> None:
    """Backfill metadata fields on an already-saved link document."""
    get_db().collection("links").document(doc_id).update({
        "title":       title,
        "description": description,
        "og_image":    og_image,
    })

def update_link_ai_tags(doc_id: str, tags: list[str]) -> None:
    """Backfill AI-generated tags on an already-saved link document."""
    get_db().collection("links").document(doc_id).update({
        "ai_tags": tags,
    })
    # Invalidate tag vocabulary cache so next AI tagging call sees fresh tags
    global _ai_tags_cache, _ai_tags_cache_ts
    _ai_tags_cache = None
    _ai_tags_cache_ts = 0.0


def get_all_ai_tags() -> list[str]:
    """Return a sorted, deduplicated list of all AI tags currently in use.

    Result is cached for 120 s to avoid a full collection scan on every link save.
    """
    global _ai_tags_cache, _ai_tags_cache_ts
    if _ai_tags_cache is not None and (time.monotonic() - _ai_tags_cache_ts) < _AI_TAGS_TTL:
        return _ai_tags_cache
    tags: set[str] = set()
    docs = get_db().collection("links").select(["ai_tags"]).stream()
    for d in docs:
        for t in (d.to_dict().get("ai_tags") or []):
            if t:
                tags.add(t)
    result = sorted(tags)
    _ai_tags_cache = result
    _ai_tags_cache_ts = time.monotonic()
    return result


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
