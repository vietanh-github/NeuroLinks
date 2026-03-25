"""Admin panel: /admin → inline keyboard menus (edit-in-place). FSM for text input."""

import os
import functools
from urllib.parse import urlparse
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import bot.firebase_client as fb

router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PER_PAGE = 5
WEB_URL  = "https://linva.net/NeuroLinks"


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
    b.button(text="🔗 Links",      callback_data="AL:0")
    b.button(text="📊 Thống kê",   callback_data="ASTAT")
    b.button(text="👥 Users",      callback_data="AU")
    if is_super:
        b.button(text="👮 Sub-admins", callback_data="ASA")
    b.button(text="🌐 Xem Web",    url=WEB_URL)
    b.adjust(2)
    return b.as_markup()

def _kb_links(links: list[dict], page: int, total_pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, link in enumerate(links, 1):
        b.button(text=f"🗑 {i}", callback_data=f"ALD:{link['id']}")
    nav_count = 0
    if page > 0:
        b.button(text="⬅️", callback_data=f"AL:{page-1}"); nav_count += 1
    b.button(text=f"📄 {page+1}/{total_pages}", callback_data="NOOP"); nav_count += 1
    if page < total_pages - 1:
        b.button(text="➡️", callback_data=f"AL:{page+1}"); nav_count += 1
    b.button(text="🔙 Menu", callback_data="AM")
    b.adjust(*([1] * len(links) + [nav_count, 1]))
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
        return (urlparse(url).hostname or url).replace("www.", "")[:40]
    except Exception:
        return url[:40]

def _links_text(links: list[dict], page: int, total_pages: int) -> str:
    lines = [f"🔗 **Links** — Trang {page+1}/{total_pages}\n"]
    for i, lk in enumerate(links, 1):
        tags    = lk.get("ai_tags") or []
        domain  = _domain(lk.get("url", ""))
        title   = lk.get("title") or domain
        tag_str = "  ".join(f"`{t}`" for t in tags[:2]) if tags else "_no tag_"
        lines.append(
            f"**{i}.** {title[:42]}\n"
            f"    🌐 `{domain}`  🏷 {tag_str}"
        )
    lines.append("\n_Nhấn số 🗑 để xóa link tương ứng_")
    return "\n".join(lines)


def _main_text(is_super: bool) -> str:
    stats  = fb.get_stats()
    users  = fb.get_all_users_with_stats()
    role   = "👑 Super Admin" if is_super else "👮 Sub-Admin"
    active = sum(1 for u in users if u["link_count"] > 0)
    return (
        f"⚙️ **NeuroLinks — Admin Panel**\n"
        f"Vai trò: {role}\n\n"
        f"🔗 Links: **{stats['total']}**   "
        f"👥 Users: **{len(users)}** ({active} active)\n\n"
        f"Chọn mục:"
    )


# ── /start ────────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    uid   = message.from_user.id
    name  = message.from_user.first_name or "bạn"
    stats = fb.get_stats()
    can_use = fb.is_user_allowed(uid, ADMIN_ID)

    if _is_super(uid):
        role_badge = "👑 Super Admin"
    elif _can_admin(uid):
        role_badge = "👮 Sub-Admin"
    elif can_use:
        role_badge = "✅ Thành viên"
    else:
        role_badge = "🔒 Chưa được cấp quyền"

    # Per-user stats
    user_doc = fb.get_all_users_with_stats()
    my_links = next((u["link_count"] for u in user_doc if u["user_id"] == uid), 0)

    text = (
        f"👋 Xin chào, **{name}**!\n\n"
        f"🧠 **NeuroLinks Bot**\n"
        f"_Thu thập link • AI tự động tags • Realtime web_\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 **{name}** — {role_badge}\n"
        f"🔗 Links bạn đã gửi: **{my_links}**\n"
        f"🌍 Tổng hệ thống: **{stats['total']}** links\n"
        f"━━━━━━━━━━━━━━━━"
    )
    if not can_use:
        text += "\n\n_💬 Liên hệ admin để được cấp quyền gửi link._"

    b = InlineKeyboardBuilder()
    b.button(text="🌐 Xem NeuroLinks", url=WEB_URL)
    if can_use:
        b.button(text="📖 Hướng dẫn", callback_data="HELP")
        b.button(text="⚙️ Cài đặt", callback_data="MYSETT")
    if _can_admin(uid):
        b.button(text="🔧 Admin Panel", callback_data="AM_START")
    b.adjust(1)
    # Track user (no link delta)
    uname = f"@{message.from_user.username}" if message.from_user.username else name
    fb.track_user_activity(uid, uname)
    await message.answer(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    await _send_help(message.answer, message.from_user.id)

async def _send_help(send_fn, uid: int):
    can_use = fb.is_user_allowed(uid, ADMIN_ID)

    cmds = (
        "🏠 /start — Dashboard cá nhân\n"
        "📖 /help — Hướng dẫn này\n"
        "🌐 /web — Mở NeuroLinks\n"
        "⚙️ /settings — Thông báo khi xử lý xong"
    )
    if _can_admin(uid):
        cmds += "\n🔧 /admin — Bảng điều khiển"

    text = f"📖 **Hướng dẫn — NeuroLinks Bot**\n\n{cmds}\n"

    if can_use:
        text += (
            "\n📎 **Cách gửi link:**\n"
            "• Paste bất kỳ URL vào chat → bot lưu ngay, AI tự động gán tags\n"
            "• Gửi nhiều link cùng lúc trong một tin nhắn ↓\n"
            "• Dùng /add `<url>` để gửi theo lệnh\n\n"
            "🤖 **AI tự động:**\n"
            "• Trích xuất tiêu đề + mô tả trang web\n"
            "• Tự gán 1–3 tags phù hợp với nội dung\n"
            "• 🔔 Thông báo khi xử lý xong (tắt được qua /settings)\n\n"
            "• Link trùng? Bot hỏi bạn muốn lưu thêm hay bỏ qua."
        )
    else:
        text += "\n_💬 Liên hệ admin để được cấp quyền gửi link._"

    b = InlineKeyboardBuilder()
    b.button(text="🌐 Mở NeuroLinks", url=WEB_URL)
    b.adjust(1)
    await send_fn(text, reply_markup=b.as_markup(), parse_mode="Markdown")


# ── /web ──────────────────────────────────────────────────────────────────────
@router.message(Command("web"))
async def cmd_web(message: Message):
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Mở NeuroLinks", url=WEB_URL)
    await message.answer(
        "🌐 **NeuroLinks** — Danh sách link của bạn:\n\n"
        "_Cập nhật realtime, lọc theo AI tags, tìm kiếm nhanh._",
        reply_markup=b.as_markup(),
        parse_mode="Markdown"
    )


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

@router.callback_query(F.data == "MYSETT")
async def cb_my_settings(cb: CallbackQuery):
    """Shortcut from /start ⚙️ Cài đặt → show settings panel."""
    uid = cb.from_user.id
    if not fb.is_user_allowed(uid, ADMIN_ID):
        await cb.answer("⛔", show_alert=True); return
    notify = fb.get_notify_pref(uid)
    await cb.message.answer(_settings_text(notify), reply_markup=_settings_kb(notify), parse_mode="Markdown")
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
    try:
        await cb.message.edit_text(_main_text(_is_super(uid)),
                                   reply_markup=_kb_main(_is_super(uid)),
                                   parse_mode="Markdown")
    except TelegramBadRequest:
        pass  # message already up-to-date
    await cb.answer()


# ── Callbacks: Stats ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "ASTAT")
async def cb_stats(cb: CallbackQuery):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    stats  = fb.get_stats()
    users  = fb.get_all_users_with_stats()
    active = sum(1 for u in users if u["link_count"] > 0)

    # Top AI tags from all users' data + global tags cache
    all_tags = fb.get_all_ai_tags()
    from collections import Counter
    tag_counter = Counter(all_tags)
    top_tags = tag_counter.most_common(10)

    lines = [
        f"📊 **Thống kê — NeuroLinks**\n",
        f"🔗 Tổng links: **{stats['total']}**",
        f"👥 Users: **{len(users)}** (active: **{active}**)",
    ]
    if top_tags:
        lines.append("\n🏷 **Top AI Tags:**")
        for tag, count in top_tags:
            bar = "█" * min(count, 10)
            lines.append(f"  `{tag}` — {bar} {count}")
    else:
        lines.append("\n_Chưa có AI tags nào._")

    # Top contributors
    if users:
        lines.append("\n🏆 **Top contributors:**")
        for u in users[:5]:
            lines.append(f"  • {u['username']} — 🔗 {u['link_count']}")

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
        try:
            await cb.message.edit_text("📭 Chưa có link nào.", reply_markup=b.as_markup())
        except TelegramBadRequest:
            pass
        return
    try:
        await cb.message.edit_text(_links_text(links, 0, total_pages),
                                   reply_markup=_kb_links(links, 0, total_pages),
                                   parse_mode="Markdown")
    except TelegramBadRequest:
        pass  # content unchanged — ignore


# ── Callbacks: Users ─────────────────────────────────────────────────────────
# “users” now means ALL users who have ever interacted with the bot,
# with link count and last-seen time, sorted by activity.
# Allowed-user whitelist is shown separately as a sub-section.

def _fmt_last_seen(ts) -> str:
    """Format a Firestore SERVER_TIMESTAMP for display."""
    from datetime import datetime, timezone
    if ts is None: return "—"
    try:
        d = ts.ToDatetime(tzinfo=timezone.utc)
        s = (datetime.now(tz=timezone.utc) - d).total_seconds()
        if s < 60:    return "vừa xong"
        if s < 3600:  return f"{int(s//60)}ph trước"
        if s < 86400: return f"{int(s//3600)}h trước"
        return d.strftime("%d/%m/%Y")
    except Exception:
        return "—"

def _tracked_users_text(users: list[dict], allowed: list[int], subs: list[int], admin_id: int) -> str:
    if not users:
        return "👥 **Users**\n\n_Chưa có ai tương tác với bot._"
    total_links = sum(u["link_count"] for u in users)
    active = sum(1 for u in users if u["link_count"] > 0)
    lines = [
        f"👥 **Users** — {len(users)} người • {active} active • 🔗 {total_links} links\n"
    ]
    for u in users[:25]:  # cap at 25 to avoid message too long
        uid   = u["user_id"]
        name  = u["username"]
        links = u["link_count"]
        seen  = _fmt_last_seen(u.get("last_seen"))
        if uid == admin_id:
            badge = " 👑"
        elif uid in subs:
            badge = " 👮"
        elif uid in allowed:
            badge = " ✅"
        else:
            badge = ""
        bar = "●" * min(links, 5)
        lines.append(f"`{uid}` {name}{badge}\n    🔗 {links} {bar}  •  🕐 {seen}")
    lines.append("\n👑 Super  👮 Sub-admin  ✅ User")
    return "\n".join(lines)

def _kb_users_tracked(can_add: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if can_add:
        b.button(text="➕ Thêm User", callback_data="AUAP")
    b.button(text="🔙 Menu", callback_data="AM")
    b.adjust(1)
    return b.as_markup()

@router.callback_query(F.data == "AU")
async def cb_users(cb: CallbackQuery, state: FSMContext):
    if not _can_admin(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.clear()
    tracked = fb.get_all_users_with_stats()
    allowed = fb.get_allowed_users()
    subs    = fb.get_sub_admins()
    text    = _tracked_users_text(tracked, allowed, subs, ADMIN_ID)
    try:
        await cb.message.edit_text(text,
                                   reply_markup=_kb_users_tracked(_is_super(cb.from_user.id)),
                                   parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await cb.answer()

@router.callback_query(F.data == "AUAP")
async def cb_user_add_prompt(cb: CallbackQuery, state: FSMContext):
    if not _is_super(cb.from_user.id): await cb.answer("⛔", show_alert=True); return
    await state.set_state(AdminFSM.adding_user)
    await cb.message.edit_text(
        "👥 Nhập **Telegram User ID** cần thêm vào whitelist:\n_(Số nguyên — lấy từ @userinfobot)_",
        reply_markup=_kb_cancel("AU"), parse_mode="Markdown")
    await cb.answer()

@router.message(AdminFSM.adding_user)
async def fsm_add_user(message: Message, state: FSMContext):
    if not _is_super(message.from_user.id): return
    try: uid = int(message.text.strip())
    except ValueError: await message.reply("❌ Nhập số nguyên hợp lệ."); return
    added = fb.add_allowed_user(uid)
    await state.clear()
    tracked = fb.get_all_users_with_stats()
    allowed = fb.get_allowed_users()
    subs    = fb.get_sub_admins()
    prefix = f"✅ Đã thêm `{uid}` vào whitelist.\n\n" if added else "⚠️ Đã tồn tại.\n\n"
    await message.answer(prefix + _tracked_users_text(tracked, allowed, subs, ADMIN_ID),
                         reply_markup=_kb_users_tracked(True), parse_mode="Markdown")


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


# ── /settings — per-user notification toggle ─────────────────────────────────

def _settings_text(notify: bool) -> str:
    status = "🔔 **Bật**" if notify else "🔕 **Tắt**"
    return (
        "⚙️ **Cài đặt cá nhân**\n\n"
        f"Thông báo khi bot xử lý xong link: {status}\n\n"
        "_Khi bật: bot sẽ gửi thêm một tin nhắn với tiêu đề trang web và tags AI sau khi xử lý xong._"
    )

def _settings_kb(notify: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    label = "🔕 Tắt thông báo" if notify else "🔔 Bật thông báo"
    b.button(text=label, callback_data="USETT_NOTIFY")
    b.adjust(1)
    return b.as_markup()

@router.message(Command("settings"))
async def cmd_settings(message: Message):
    uid = message.from_user.id
    if not fb.is_user_allowed(uid, ADMIN_ID):
        await message.reply("⛔ Bạn không có quyền sử dụng bot này."); return
    notify = fb.get_notify_pref(uid)
    await message.answer(_settings_text(notify), reply_markup=_settings_kb(notify), parse_mode="Markdown")

@router.callback_query(F.data == "USETT_NOTIFY")
async def cb_toggle_notify(cb: CallbackQuery):
    uid = cb.from_user.id
    if not fb.is_user_allowed(uid, ADMIN_ID):
        await cb.answer("⛔", show_alert=True); return
    current = fb.get_notify_pref(uid)
    new_val = not current
    fb.set_notify_pref(uid, new_val)
    status = "🔔 Đã bật" if new_val else "🔕 Đã tắt"
    await cb.answer(f"{status} thông báo")
    try:
        await cb.message.edit_text(_settings_text(new_val),
                                   reply_markup=_settings_kb(new_val),
                                   parse_mode="Markdown")
    except TelegramBadRequest:
        pass
