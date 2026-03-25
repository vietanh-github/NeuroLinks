"""Link handler: save link immediately with smart duplicate detection."""

import re
import os
import asyncio
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import bot.firebase_client as fb
from bot.metadata import fetch_metadata
from bot.ai_tagger import ai_generate_tags

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
URL_RE = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)
DEFAULT_CATEGORY = "Chưa phân loại"
WEB_URL = "https://linva.net/NeuroLinks"

# _pending_cat: message_id → {"uid": int, "doc_id": str}
# _pending_dup: message_id → {"uid": int, "url": str, "existing": dict}
_pending_cat: dict[int, dict]  = {}
_pending_dup: dict[int, dict]  = {}

def _allowed(uid: int) -> bool:
    return fb.is_user_allowed(uid, ADMIN_ID)

def _username(user) -> str:
    return f"@{user.username}" if user.username else user.full_name

def _fmt_time(ts) -> str:
    try:
        d = ts.toDate() if hasattr(ts, "toDate") else datetime.fromtimestamp(ts.seconds, tz=timezone.utc)
        s = (datetime.now(tz=timezone.utc) - d).total_seconds()
        if s < 60:    return "vừa xong"
        if s < 3600:  return f"{int(s//60)}ph trước"
        if s < 86400: return f"{int(s//3600)}h trước"
        return d.strftime("%d/%m/%Y")
    except Exception:
        return "—"

def _web_kb() -> InlineKeyboardBuilder:
    """Single button to open the website."""
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Xem trên NeuroLinks", url=WEB_URL)
    return b

# ── Keyboards ─────────────────────────────────────────────────────────────────

def _cat_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for cat in fb.get_categories():
        b.button(text=cat, callback_data=f"cat:{cat}")
    b.button(text="⏩ Bỏ qua", callback_data="catskip")
    b.adjust(3)
    return b

def _dup_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Vẫn lưu thêm",      callback_data="dupS")
    b.button(text="🔄 Đổi category bản cũ", callback_data="dupU")
    b.button(text="❌ Bỏ qua",             callback_data="dupX")
    b.adjust(1)
    return b

# ── Core: process URL ─────────────────────────────────────────────────────────

async def _process_url(url: str, user, reply_fn):
    """Check for duplicate, then either notify or save immediately."""
    existing = fb.find_link_by_url(url)

    if existing:
        # Duplicate detected — store state, ask user
        cat   = existing.get("category", "—")
        uname = existing.get("username", "—")
        ts    = _fmt_time(existing.get("created_at"))
        sent = await reply_fn(
            f"⚠️ *Link này đã được lưu trước đó!*\n\n"
            f"🔗 `{url}`\n"
            f"📁 {cat}  ·  👤 {uname}  ·  🕐 {ts}\n\n"
            f"Bạn muốn làm gì?",
            reply_markup=_dup_kb().as_markup(),
            parse_mode="Markdown"
        )
        _pending_dup[sent.message_id] = {"uid": user.id, "url": url, "existing": existing}
    else:
        # New link — save immediately then ask for category
        doc_id = fb.add_link(url=url, category=DEFAULT_CATEGORY,
                             user_id=user.id, username=_username(user))
        # Fire background metadata fetch (does NOT block the reply)
        asyncio.create_task(_fetch_and_save(doc_id, url))
        # Category picker + web button together
        b = _cat_kb()
        b.button(text="🌐 Xem trên NeuroLinks", url=WEB_URL)
        b.adjust(3, 1, 1)  # 3 cats per row, skip button, web button
        sent = await reply_fn(
            f"✅ *Đã lưu link!*\n🔗 `{url}`\n📁 _{DEFAULT_CATEGORY}_\n\nChọn category để cập nhật:",
            reply_markup=b.as_markup(),
            parse_mode="Markdown"
        )
        _pending_cat[sent.message_id] = {"uid": user.id, "doc_id": doc_id}

# ── Background metadata + AI tag fetch ──────────────────────────────────────────

async def _fetch_and_save(doc_id: str, url: str) -> None:
    """Fetch page metadata + AI tags and write back to Firestore. Runs in background."""
    # 1. Fetch HTML metadata
    meta = await fetch_metadata(url)
    title       = meta.get("title", "")
    description = meta.get("description", "")
    og_image    = meta.get("og_image", "")
    if title or description:
        fb.update_link_metadata(doc_id, title=title, description=description, og_image=og_image)

    # 2. AI auto-tagging (uses title + description as context for better tags)
    tags = await ai_generate_tags(url, title=title, description=description)
    if tags:
        fb.update_link_ai_tags(doc_id, tags)

# ── /add command ──────────────────────────────────────────────────────────────
@router.message(Command("add"))
async def cmd_add(message: Message):
    if not _allowed(message.from_user.id):
        await message.reply("⛔ Bạn không có quyền sử dụng bot này."); return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.reply("📎 Cú pháp: `/add <url> [category]`", parse_mode="Markdown"); return
    url = parts[1]
    if not URL_RE.match(url):
        await message.reply("❌ URL không hợp lệ."); return

    # If category provided inline, skip duplicate check (explicit intent)
    if len(parts) == 3:
        cats = fb.get_categories()
        cat  = parts[2]
        if cat not in cats:
            await message.reply(
                f"❌ Category `{cat}` không tồn tại.\nHiện có: {', '.join(cats)}",
                parse_mode="Markdown"); return
        fb.add_link(url=url, category=cat, user_id=message.from_user.id,
                    username=_username(message.from_user))
        await message.reply(f"✅ Đã lưu vào **{cat}**!", parse_mode="Markdown"); return

    await _process_url(url, message.from_user, message.reply)


# ── Auto-detect URL ───────────────────────────────────────────────────────────
@router.message(F.text)
async def auto_detect(message: Message):
    if not _allowed(message.from_user.id): return
    urls = URL_RE.findall(message.text)
    if not urls: return
    # Deduplicate URLs in the same message while preserving order
    urls = list(dict.fromkeys(urls))
    for url in urls:
        await _process_url(url, message.from_user, message.reply)


# ── Duplicate decision callbacks ──────────────────────────────────────────────

@router.callback_query(F.data == "dupS")
async def dup_save(cb: CallbackQuery):
    mid = cb.message.message_id
    state = _pending_dup.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_dup[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    url = state["url"]
    doc_id = fb.add_link(url=url, category=DEFAULT_CATEGORY,
                         user_id=state["uid"], username=_username(cb.from_user))
    
    b = _cat_kb()
    b.button(text="🌐 Xem trên NeuroLinks", url=WEB_URL)
    b.adjust(3, 1, 1)

    _pending_cat[mid] = {"uid": state["uid"], "doc_id": doc_id}
    await cb.message.edit_text(
        f"✅ *Đã lưu thêm!*\n🔗 `{url}`\n📁 _{DEFAULT_CATEGORY}_\n\nChọn category:",
        reply_markup=b.as_markup(),
        parse_mode="Markdown"
    )
    await cb.answer()

@router.callback_query(F.data == "dupU")
async def dup_update(cb: CallbackQuery):
    mid = cb.message.message_id
    state = _pending_dup.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_dup[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    # Reuse the existing doc — put it in pending_cat to update category
    _pending_cat[mid] = {"uid": state["uid"], "doc_id": state["existing"]["id"]}
    await cb.message.edit_text(
        f"🔄 Chọn category mới cho bản *đã có*:",
        reply_markup=_cat_kb().as_markup(),
        parse_mode="Markdown"
    )
    await cb.answer()

@router.callback_query(F.data == "dupX")
async def dup_cancel(cb: CallbackQuery):
    mid = cb.message.message_id
    state = _pending_dup.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_dup[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    await cb.message.edit_text("❌ *Đã bỏ qua.* Link không được lưu thêm.", parse_mode="Markdown")
    await cb.answer()


# ── Category selection callbacks ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("cat:"))
async def on_cat_selected(cb: CallbackQuery):
    mid = cb.message.message_id
    cat = cb.data.split(":", 1)[1]
    
    state = _pending_cat.pop(mid, None)
    if not state: await cb.answer("⚠️ Không tìm thấy link.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_cat[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return
        
    fb.update_link_category(state["doc_id"], cat)
    await cb.message.edit_text(
        f"✅ *Đã cập nhật category!*\n📁 **{cat}**",
        reply_markup=_web_kb().as_markup(),
        parse_mode="Markdown"
    )
    await cb.answer(f"✅ Category: {cat}")

@router.callback_query(F.data == "catskip")
async def on_cat_skip(cb: CallbackQuery):
    mid = cb.message.message_id
    state = _pending_cat.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_cat[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    await cb.message.edit_text(f"📁 Giữ category: _{DEFAULT_CATEGORY}_", parse_mode="Markdown")
    await cb.answer("⏩ Bỏ qua")
