"""Admin panel: /admin → inline keyboard menus (edit-in-place). FSM for text input."""

import os
import functools
from urllib.parse import urlparse
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import bot.firebase_client as fb

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PER_PAGE = 5
WEB_URL = "https://linva.net/NeuroLinks"


# ── FSM ───────────────────────────────────────────────────────────────────────
class AdminFSM(StatesGroup):
    adding_category  = State()
    adding_user      = State()
    adding_sub_admin = State()


# ── Auth ──────────────────────────────────────────────────────────────────────
def _is_super(uid: int) -> bool:
    return uid == ADMIN_ID

def _can_admin(uid: int) -> bool:
    return fb.is_sub_admin(uid, ADMIN_ID)


# ── Keyboard builders ─────────────────────────────────────────────────────────
def _kb_main(is_super: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Links",       callback_data="AL:0")
    b.button(text="📊 Thống kê",    callback_data="ASTAT")
    b.button(text="📁 Categories",  callback_data="AC")
    b.button(text="👥 Users",       callback_data="AU")
    if is_super:
        b.button(text="👮 Sub-admins", callback_data="ASA")
    b.adjust(2)
    return b.as_markup()

def _kb_links(links: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, link in enumerate(links, 1):
        b.button(text=f"🗑 {i}", callback_data=f"ALD:{link['id']}")
        b.button(text=f"✏️ {i}", callback_data=f"ALC:{link['id']}")
    # navigation row
    nav_count = 0
    if page > 0:
        b.button(text="⬅️", callback_data=f"AL:{page-1}"); nav_count += 1
    b.button(text=f"📄{page+1}/{total_pages}", callback_data="NOOP"); nav_count += 1
    if page < total_pages - 1:
        b.button(text="➡️", callback_data=f"AL:{page+1}"); nav_count += 1
    b.button(text="🔙 Menu", callback_data="AM")
    b.adjust(*([2] * len(links) + [nav_count, 1]))
    return b.as_markup()

def _kb_cat_select(doc_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cat in fb.get_categories():
        b.button(text=cat, callback_data=f"ALCS:{doc_id}:{cat}")
    b.button(text="❌ Hủy", callback_data="AL:0")
    b.adjust(3, 1)
    return b.as_markup()

def _kb_categories(cats: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for cat in cats:
        b.button(text=f"🗑 {cat}", callback_data=f"ACD:{cat}")
    b.button(text="➕ Thêm", callback_data="ACAP")
    b.button(text="🔙 Menu",  callback_data="AM")
    b.adjust(*([1] * len(cats) + [1, 1]))
    return b.as_markup()

def _kb_users(users: list[int], can_add: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        b.button(text=f"🗑 {u}", callback_data=f"AUD:{u}")
    if can_add:
        b.button(text="➕ Thêm User", callback_data="AUAP")
    b.button(text="🔙 Menu", callback_data="AM")
    b.adjust(*([1] * len(users) + ([1] if can_add else []) + [1]))
    return b.as_markup()

def _kb_subadmins(subs: list[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in subs:
        b.button(text=f"🗑 {u}", callback_data=f"ASAD:{u}")
    b.button(text="➕ Thêm Sub-admin", callback_data="ASAAP")
    b.button(text="🔙 Menu", callback_data="AM")
    b.adjust(*([1] * len(subs) + [1, 1]))
    return b.as_markup()

def _kb_cancel(back: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Hủy", callback_data=back)
    return b.as_markup()


# ── Text helpers ──────────────────────────────────────────────────────────────
def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or url).replace("www.", "")[:35]
    except Exception:
        return url[:35]

def _links_text(links: list[dict], page: int, total_pages: int) -> str:
    lines = [f"📋 **Links** — Trang {page+1}/{total_pages}\n"]
    for i, lk in enumerate(links, 1):
        cat   = lk.get("category", "—")
        uname = lk.get("username", "—")
        lines.append(f"{i}. **{_domain(lk.get('url',''))}** `[{cat}]` {uname}")
    lines.append("\n_🗑 xóa  ✏️ đổi category_")
    return "\n".join(lines)

def _main_text(is_super: bool) -> str:
    stats = fb.get_stats()
    role  = "👑 Super Admin" if is_super else "👮 Sub-Admin"
    return f"⚙️ **Admin Panel** — {role}\n\n📊 Tổng: **{stats['total']}** links\n\nChọn mục:"


# ── /start ────────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    uid  = message.from_user.id
    name = message.from_user.first_name or "bạn"
    if _is_super(uid):                      role = "👑 Super Admin"
    elif _can_admin(uid):                   role = "👮 Sub-Admin"
    elif fb.is_user_allowed(uid, ADMIN_ID): role = "✅ Thành viên"
    else:                                   role = "❌ Chưa được cấp quyền"

    stats = fb.get_stats()
    can_use = fb.is_user_allowed(uid, ADMIN_ID)

    text = (
        f"👋 Xin chào **{name}**!\n\n"
        f"🔗 **NeuroLinks** thu thập link từ Telegram và hiển thị trên web theo thời gian thực.\n\n"
        f"Vai trò của bạn: {role}\n"
        f"📊 Tổng cộng: **{stats['total']}** links đã lưu"
    )
    if not can_use:
        text += "\n\n_Liên hệ admin để được cấp quyền gửi link._"

    b = InlineKeyboardBuilder()
    b.button(text="🌐 Xem NeuroLinks", url=WEB_URL)
    if _can_admin(uid):
        b.button(text="⚙️ Admin Panel", callback_data="AM_START")
    b.button(text="📖 Hướng dẫn", callback_data="HELP")
    b.adjust(1)

    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    uid = message.from_user.id
    await _send_help(message.answer, uid)

async def _send_help(send_fn, uid: int):
    text = "📖 **Hướng dẫn NeuroLinks**\n\n"
    text += "• /start — Thông tin & menu chính\n"
    text += "• /help — Hướng dẫn này\n"
    if fb.is_user_allowed(uid, ADMIN_ID):
        text += (
            "\n📎 **Gửi link:**\n"
            "• Paste URL bất kỳ → bot lưu ngay + hỏi category\n"
            "• /add `<url> [category]` — thêm kèm category\n"
            "\n_Link trùng? Bot sẽ hỏi bạn muốn làm gì._\n"
        )
    if _can_admin(uid):
        text += "\n⚙️ /admin — Bảng điều khiển admin\n"
    if not fb.is_user_allowed(uid, ADMIN_ID):
        text += "\n_Liên hệ admin để được cấp quyền._"

    b = InlineKeyboardBuilder()
    b.button(text="🌐 Xem kết quả trên web", url=WEB_URL)
    b.adjust(1)
    await send_fn(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ── Callback shortcuts from /start ───────────────────────────────────────────
@router.callback_query(F.data == "AM_START")
async def cb_am_start(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    uid = cb.from_user.id
    await cb.message.answer(_main_text(_is_super(uid)),
                            reply_markup=_kb_main(_is_super(uid)),
                            parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data == "HELP")
async def cb_help(cb: CallbackQuery):
    await _send_help(cb.message.answer, cb.from_user.id)
    await cb.answer()


# ── /admin ────────────────────────────────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not _can_admin(message.from_user.id):
        await message.reply("⛔ Bạn không có quyền truy cập admin panel.")
        return
    await state.clear()
    uid = message.from_user.id
    await message.answer(_main_text(_is_super(uid)),
                         reply_markup=_kb_main(_is_super(uid)),
                         parse_mode="Markdown")


# ── Callbacks: NOOP / Main menu ───────────────────────────────────────────────
@router.callback_query(F.data == "NOOP")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()

@router.callback_query(F.data == "AM")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    uid = cb.from_user.id
    await cb.message.edit_text(_main_text(_is_super(uid)),
                               reply_markup=_kb_main(_is_super(uid)),
                               parse_mode="Markdown")
    await cb.answer()


# ── Callbacks: Stats ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "ASTAT")
async def cb_stats(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    stats = fb.get_stats()
    lines = [f"📊 **Thống kê**\n\nTổng: **{stats['total']}** links\n"]
    if stats["by_category"]:
        lines.append("**Theo category:**")
        for cat, n in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat}: {n}")
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Menu", callback_data="AM")
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup(), parse_mode="Markdown")
    await cb.answer()


# ── Callbacks: Links ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("AL:"))
async def cb_links(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    page = int(cb.data.split(":")[1])
    links, total = fb.get_links_paginated(page, PER_PAGE)
    total_pages  = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if not links and page > 0:
        page, (links, total) = 0, fb.get_links_paginated(0, PER_PAGE)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if not links:
        b = InlineKeyboardBuilder(); b.button(text="🔙 Menu", callback_data="AM")
        await cb.message.edit_text("📭 Chưa có link nào.", reply_markup=b.as_markup())
        await cb.answer(); return
    await cb.message.edit_text(_links_text(links, page, total_pages),
                               reply_markup=_kb_links(links, page, total_pages),
                               parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data.startswith("ALD:"))
async def cb_link_delete(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    fb.delete_link(cb.data[4:])
    await cb.answer("✅ Đã xóa!")
    links, total = fb.get_links_paginated(0, PER_PAGE)
    total_pages  = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if not links:
        b = InlineKeyboardBuilder(); b.button(text="🔙 Menu", callback_data="AM")
        await cb.message.edit_text("📭 Chưa có link nào.", reply_markup=b.as_markup()); return
    await cb.message.edit_text(_links_text(links, 0, total_pages),
                               reply_markup=_kb_links(links, 0, total_pages),
                               parse_mode="Markdown")

@router.callback_query(F.data.startswith("ALC:"))
async def cb_link_change_cat(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    doc_id = cb.data[4:]
    await cb.message.edit_text(f"✏️ Chọn category mới:",
                               reply_markup=_kb_cat_select(doc_id))
    await cb.answer()

@router.callback_query(F.data.startswith("ALCS:"))
async def cb_link_cat_set(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    parts = cb.data.split(":", 2)
    if len(parts) < 3: await cb.answer("❌"); return
    doc_id, cat = parts[1], parts[2]
    fb.update_link_category(doc_id, cat)
    await cb.answer(f"✅ Đổi thành [{cat}]")
    links, total = fb.get_links_paginated(0, PER_PAGE)
    total_pages  = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    await cb.message.edit_text(_links_text(links, 0, total_pages),
                               reply_markup=_kb_links(links, 0, total_pages),
                               parse_mode="Markdown")


# ── Callbacks: Categories ─────────────────────────────────────────────────────
def _cat_text(cats: list[str]) -> str:
    body = "\n".join(f"• {c}" for c in cats) if cats else "_Chưa có_"
    return f"📁 **Categories** ({len(cats)})\n_🗑 để xóa_\n\n{body}"

@router.callback_query(F.data == "AC")
async def cb_categories(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    cats = fb.get_categories()
    await cb.message.edit_text(_cat_text(cats), reply_markup=_kb_categories(cats), parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data.startswith("ACD:"))
async def cb_cat_delete(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    fb.remove_category(cb.data[4:])
    await cb.answer("✅ Đã xóa")
    cats = fb.get_categories()
    await cb.message.edit_text(_cat_text(cats), reply_markup=_kb_categories(cats), parse_mode="Markdown")

@router.callback_query(F.data == "ACAP")
async def cb_cat_add_prompt(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.set_state(AdminFSM.adding_category)
    await cb.message.edit_text("📁 Nhập tên category mới (1–20 ký tự):",
                               reply_markup=_kb_cancel("AC"))
    await cb.answer()

@router.message(AdminFSM.adding_category)
async def fsm_add_category(message: Message, state: FSMContext):
    if not _can_admin(message.from_user.id): return
    name = message.text.strip()
    if not 1 <= len(name) <= 20:
        await message.reply("❌ Tên phải từ 1–20 ký tự."); return
    added = fb.add_category(name)
    await state.clear()
    cats = fb.get_categories()
    prefix = f"✅ Đã thêm **{name}**\n\n" if added else "⚠️ Đã tồn tại.\n\n"
    await message.answer(prefix + _cat_text(cats), reply_markup=_kb_categories(cats), parse_mode="Markdown")


# ── Callbacks: Users ──────────────────────────────────────────────────────────
def _users_text(users: list[int]) -> str:
    body = "\n".join(f"• `{u}`" for u in users) if users else "_Trống_"
    return f"👥 **Users được phép** ({len(users)})\n\n{body}"

@router.callback_query(F.data == "AU")
async def cb_users(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    users = fb.get_allowed_users()
    await cb.message.edit_text(_users_text(users),
                               reply_markup=_kb_users(users, _is_super(cb.from_user.id)),
                               parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data.startswith("AUD:"))
async def cb_user_delete(cb: CallbackQuery):
    if not _is_super(cb.from_user.id): await cb.answer("⛔ Chỉ super admin.", show_alert=True); return
    fb.remove_allowed_user(int(cb.data[4:]))
    await cb.answer("✅ Đã xóa")
    users = fb.get_allowed_users()
    await cb.message.edit_text(_users_text(users),
                               reply_markup=_kb_users(users, True), parse_mode="Markdown")

@router.callback_query(F.data == "AUAP")
async def cb_user_add_prompt(cb: CallbackQuery, state: FSMContext):
    if not _is_super(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.set_state(AdminFSM.adding_user)
    await cb.message.edit_text(
        "👥 Nhập **Telegram User ID** cần thêm:\n_(Số nguyên, lấy từ @userinfobot)_",
        reply_markup=_kb_cancel("AU"), parse_mode="Markdown")
    await cb.answer()

@router.message(AdminFSM.adding_user)
async def fsm_add_user(message: Message, state: FSMContext):
    if not _is_super(message.from_user.id): return
    try: uid = int(message.text.strip())
    except ValueError: await message.reply("❌ Nhập số nguyên hợp lệ."); return
    added = fb.add_allowed_user(uid)
    await state.clear()
    users = fb.get_allowed_users()
    prefix = f"✅ Đã thêm `{uid}`\n\n" if added else "⚠️ Đã tồn tại.\n\n"
    await message.answer(prefix + _users_text(users),
                         reply_markup=_kb_users(users, True), parse_mode="Markdown")


# ── Callbacks: Sub-admins (super admin only) ──────────────────────────────────
def _subs_text(subs: list[int]) -> str:
    body = "\n".join(f"• `{u}`" for u in subs) if subs else "_Chưa có_"
    return f"👮 **Sub-admins** ({len(subs)})\n_🗑 để xóa_\n\n{body}"

@router.callback_query(F.data == "ASA")
async def cb_subadmins(cb: CallbackQuery, state: FSMContext):
    if not _is_super(cb.from_user.id): await cb.answer("⛔ Chỉ super admin.", show_alert=True); return
    await state.clear()
    subs = fb.get_sub_admins()
    await cb.message.edit_text(_subs_text(subs), reply_markup=_kb_subadmins(subs), parse_mode="Markdown")
    await cb.answer()

@router.callback_query(F.data.startswith("ASAD:"))
async def cb_subadmin_delete(cb: CallbackQuery):
    if not _is_super(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    fb.remove_sub_admin(int(cb.data[5:]))
    await cb.answer("✅ Đã xóa")
    subs = fb.get_sub_admins()
    await cb.message.edit_text(_subs_text(subs), reply_markup=_kb_subadmins(subs), parse_mode="Markdown")

@router.callback_query(F.data == "ASAAP")
async def cb_subadmin_add_prompt(cb: CallbackQuery, state: FSMContext):
    if not _is_super(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.set_state(AdminFSM.adding_sub_admin)
    await cb.message.edit_text(
        "👮 Nhập **User ID** của sub-admin mới:\n_(Lấy từ @userinfobot)_",
        reply_markup=_kb_cancel("ASA"), parse_mode="Markdown")
    await cb.answer()

@router.message(AdminFSM.adding_sub_admin)
async def fsm_add_subadmin(message: Message, state: FSMContext):
    if not _is_super(message.from_user.id): return
    try: uid = int(message.text.strip())
    except ValueError: await message.reply("❌ Nhập số nguyên hợp lệ."); return
    added = fb.add_sub_admin(uid)
    await state.clear()
    subs = fb.get_sub_admins()
    prefix = f"✅ Đã thêm sub-admin `{uid}`\n\n" if added else "⚠️ Đã tồn tại.\n\n"
    await message.answer(prefix + _subs_text(subs), reply_markup=_kb_subadmins(subs), parse_mode="Markdown")
