"""Link handler: save link immediately with smart duplicate detection.

Category picker removed — AI tags are the sole classification system.
"""

import re
import os
import asyncio
from datetime import datetime, timezone
from aiogram import Bot, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import bot.firebase_client as fb
from bot.metadata import fetch_metadata
from bot.ai_tagger import ai_generate_tags

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
URL_RE = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)
WEB_URL = "https://linva.net/NeuroLinks"

# _pending_dup: message_id → {"uid": int, "url": str, "existing": dict}
_pending_dup: dict[int, dict] = {}


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
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Xem trên NeuroLinks", url=WEB_URL)
    return b

def _dup_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Vẫn lưu thêm", callback_data="dupS")
    b.button(text="🗑 Xóa",          callback_data="dupDEL")
    b.button(text="❌ Bỏ qua",       callback_data="dupX")
    b.adjust(2, 1)  # row1: [Lưu thêm | Xóa], row2: [Bỏ qua]
    return b

# ── Core: process URL ─────────────────────────────────────────────────────────

async def _process_url(url: str, user, reply_fn, bot: Bot | None = None):
    """Check for duplicate, then either notify or save immediately."""
    existing = fb.find_link_by_url(url)

    if existing:
        uname = existing.get("username", "—")
        ts    = _fmt_time(existing.get("created_at"))
        tags  = existing.get("ai_tags") or []
        tag_str = ("  🏷 " + "  ".join(tags)) if tags else ""
        sent = await reply_fn(
            f"⚠️ *Link này đã được lưu trước đó!*\n\n"
            f"🔗 `{url}`\n"
            f"👤 {uname}  ·  🕐 {ts}{tag_str}\n\n"
            f"Bạn muốn làm gì?",
            reply_markup=_dup_kb().as_markup(),
            parse_mode="Markdown"
        )
        _pending_dup[sent.message_id] = {"uid": user.id, "url": url, "existing": existing, "bot": bot}
    else:
        # New link — save, track user in background, fire enrichment, reply
        doc_id = fb.add_link(url=url, category="", user_id=user.id, username=_username(user))
        asyncio.create_task(asyncio.to_thread(fb.track_user_activity, user.id, _username(user), 1))
        asyncio.create_task(_fetch_and_save(doc_id, url, user.id, user.id, bot, _username(user)))
        await reply_fn(
            f"✅ *Đã lưu link!*\n🔗 `{url}`\n\n"
            f"🤖 _AI đang tự động tạo tags…_",
            reply_markup=_web_kb().as_markup(),
            parse_mode="Markdown"
        )

# ── Background metadata + AI tag fetch ─────────────────────────────────────────────────────────

async def _fetch_and_save(doc_id: str, url: str,
                          user_id: int = 0, chat_id: int = 0,
                          bot: Bot | None = None,
                          username: str = "") -> None:
    """Fetch page metadata + AI tags and write back to Firestore. Runs in background.

    If `bot` is provided and the user has notify_done=True, sends a follow-up
    message with the extracted title and AI-generated tags.
    """
    meta = await fetch_metadata(url)
    title       = meta.get("title", "")
    description = meta.get("description", "")
    og_image    = meta.get("og_image", "")
    if title or description:
        fb.update_link_metadata(doc_id, title=title, description=description, og_image=og_image)

    # Fetch existing tags so AI can harmonise (reuse existing, avoid near-duplicates)
    existing_tags = fb.get_all_ai_tags()
    tags = await ai_generate_tags(url, title=title, description=description,
                                  existing_tags=existing_tags)
    if tags:
        fb.update_link_ai_tags(doc_id, tags)

    # ── Follow-up notification ────────────────────────────────────
    if bot and chat_id and user_id:
        try:
            notify = await asyncio.to_thread(fb.get_notify_pref, user_id)
        except Exception:
            notify = True
        if notify:
            title_line = f"📌 *{title}*\n" if title else ""
            tag_line   = "  ".join(f"`{t}`" for t in tags) if tags else "_chưa phân loại_"
            username_line = f"👤 `{username}`\n" if username else ""
            text = (
                f"✅ *Xử lý xong!*\n\n"
                f"{title_line}"
                f"🔗 {url}\n"
                f"{username_line}"
                f"🏷 *Tags:* {tag_line}"
            )
            kb = InlineKeyboardBuilder()
            kb.button(text="🌐 Xem NeuroLinks", url=WEB_URL)
            try:
                await bot.send_message(chat_id, text,
                                       reply_markup=kb.as_markup(),
                                       parse_mode="Markdown")
            except Exception:
                pass  # silently ignore send failures


# ── /add command ──────────────────────────────────────────────────────────────
@router.message(Command("add"))
async def cmd_add(message: Message):
    if not _allowed(message.from_user.id):
        await message.reply("⛔ Bạn không có quyền sử dụng bot này."); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("📎 Cú pháp: `/add <url>`", parse_mode="Markdown"); return
    url = parts[1].strip()
    if not URL_RE.match(url):
        await message.reply("❌ URL không hợp lệ."); return
    await _process_url(url, message.from_user, message.reply, bot=message.bot)


# ── Auto-detect URL ───────────────────────────────────────────────────────────
@router.message(F.text)
async def auto_detect(message: Message):
    if not _allowed(message.from_user.id): return
    urls = URL_RE.findall(message.text)
    if not urls: return
    urls = list(dict.fromkeys(urls))
    for url in urls:
        await _process_url(url, message.from_user, message.reply, bot=message.bot)


# ── Duplicate decision callbacks ──────────────────────────────────────────────

@router.callback_query(F.data == "dupS")
async def dup_save(cb: CallbackQuery):
    mid = cb.message.message_id
    state = _pending_dup.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_dup[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    url      = state["url"]
    existing = state["existing"]
    bot      = state.get("bot")
    uname    = _username(cb.from_user)

    # Delete old entry, then save fresh (re-tag)
    if existing.get("id"):
        fb.delete_link(existing["id"])
    doc_id = fb.add_link(url=url, category="", user_id=state["uid"], username=uname)
    asyncio.create_task(asyncio.to_thread(fb.track_user_activity, state["uid"], uname, 1))
    asyncio.create_task(_fetch_and_save(doc_id, url, state["uid"], state["uid"], bot, uname))
    await cb.message.edit_text(
        f"✅ *Đã lưu lại!*\n🔗 `{url}`\n\n🤖 _AI đang tạo tags mới…_",
        reply_markup=_web_kb().as_markup(),
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


@router.callback_query(F.data == "dupDEL")
async def dup_delete(cb: CallbackQuery):
    """Xóa sạch link cũ, không lưu thêm gì."""
    mid = cb.message.message_id
    state = _pending_dup.pop(mid, None)
    if not state: await cb.answer("⚠️ Đã hết hạn.", show_alert=True); return
    if cb.from_user.id != state["uid"]:
        _pending_dup[mid] = state
        await cb.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    existing = state["existing"]
    url      = state["url"]
    if existing.get("id"):
        fb.delete_link(existing["id"])

    await cb.message.edit_text(
        f"🗑 *Đã xóa link!*\n🔗 `{url}`",
        parse_mode="Markdown"
    )
    await cb.answer("✅ Đã xóa")
