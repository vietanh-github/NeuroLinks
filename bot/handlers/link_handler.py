"""Link handler: save link immediately, then optionally update category."""

import re
import os
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import bot.firebase_client as fb

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
URL_RE = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.IGNORECASE)

DEFAULT_CATEGORY = "Chưa phân loại"

# pending: user_id → doc_id (saved link waiting for category update)
_pending: dict[int, str] = {}


def _allowed(uid: int) -> bool:
    return fb.is_user_allowed(uid, ADMIN_ID)


def _cat_kb(user_id: int) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    for cat in fb.get_categories():
        b.button(text=cat, callback_data=f"cat:{user_id}:{cat}")
    b.button(text="⏩ Bỏ qua", callback_data=f"catskip:{user_id}")
    b.adjust(3)
    return b


def _save_and_prompt(url: str, user, reply_fn) -> str:
    """Save link immediately with default category, return doc_id."""
    username = f"@{user.username}" if user.username else user.full_name
    doc_id = fb.add_link(url=url, category=DEFAULT_CATEGORY,
                         user_id=user.id, username=username)
    return doc_id


# ── /add command ──────────────────────────────────────────────────────────────
@router.message(Command("add"))
async def cmd_add(message: Message):
    if not _allowed(message.from_user.id):
        await message.reply("⛔ Bạn không có quyền sử dụng bot này.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.reply("📎 Cú pháp: `/add <url> [category]`", parse_mode="Markdown")
        return
    url = parts[1]
    if not URL_RE.match(url):
        await message.reply("❌ URL không hợp lệ."); return

    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    cats = fb.get_categories()

    # Category provided inline → save directly with that category
    if len(parts) == 3:
        cat = parts[2]
        if cat not in cats:
            await message.reply(
                f"❌ Category `{cat}` không tồn tại.\nHiện có: {', '.join(cats)}",
                parse_mode="Markdown"); return
        fb.add_link(url=url, category=cat, user_id=message.from_user.id, username=username)
        await message.reply(f"✅ Đã lưu vào **{cat}**!", parse_mode="Markdown")
        return

    # No category → save immediately with default, then ask
    doc_id = fb.add_link(url=url, category=DEFAULT_CATEGORY,
                         user_id=message.from_user.id, username=username)
    _pending[message.from_user.id] = doc_id
    await message.reply(
        f"✅ Đã lưu link!\n🔗 `{url}`\n📁 Category: _{DEFAULT_CATEGORY}_\n\nChọn category để cập nhật:",
        reply_markup=_cat_kb(message.from_user.id).as_markup(),
        parse_mode="Markdown"
    )


# ── Auto-detect URL ───────────────────────────────────────────────────────────
@router.message(F.text)
async def auto_detect(message: Message):
    if not _allowed(message.from_user.id): return
    urls = URL_RE.findall(message.text)
    if not urls: return

    url = urls[0]
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name

    # Save immediately with default category
    doc_id = fb.add_link(url=url, category=DEFAULT_CATEGORY,
                         user_id=message.from_user.id, username=username)
    _pending[message.from_user.id] = doc_id

    await message.reply(
        f"✅ Đã lưu link!\n🔗 `{url}`\n📁 Category: _{DEFAULT_CATEGORY}_\n\nChọn category để cập nhật:",
        reply_markup=_cat_kb(message.from_user.id).as_markup(),
        parse_mode="Markdown"
    )


# ── Category callback ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cat:"))
async def on_cat_selected(callback: CallbackQuery):
    _, uid_str, cat = callback.data.split(":", 2)
    uid = int(uid_str)
    if callback.from_user.id != uid:
        await callback.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    doc_id = _pending.pop(uid, None)
    if not doc_id:
        await callback.answer("⚠️ Không tìm thấy link. Có thể đã hết hạn.", show_alert=True); return

    fb.update_link_category(doc_id, cat)
    await callback.message.edit_text(
        f"✅ Đã cập nhật category!\n📁 **{cat}**",
        parse_mode="Markdown"
    )
    await callback.answer(f"✅ Category: {cat}")


# ── Skip category callback ────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("catskip:"))
async def on_cat_skip(callback: CallbackQuery):
    uid = int(callback.data.split(":")[1])
    if callback.from_user.id != uid:
        await callback.answer("❌ Không phải lượt của bạn.", show_alert=True); return

    _pending.pop(uid, None)
    await callback.message.edit_text(
        f"📁 Đã giữ category mặc định: _{DEFAULT_CATEGORY}_",
        parse_mode="Markdown"
    )
    await callback.answer("⏩ Bỏ qua")
