import asyncio
import logging
import sqlite3
import os
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8904383952:AAEgL5qOyAFJrweyrTrGDDcDBJppUQIEHnI"
MODERATION_CHAT_ID = -5157134920
TARGET_CHANNEL_ID = -1003932701423
CHANNEL_USERNAME = "твой_юзернейм_канала_без_собачки"

SECRET_ADMIN_CODE = "ДЖЕРРИ_АДМИН_2026" 
# ------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- МИНИ-ВЕБ СЕРВЕР ДЛЯ ОБХОДА БЛОКИРОВКИ RENDER ---
async def handle(request):
    return web.Response(text="Бот работает в фоновом режиме 24/7!")

async def start_webhook_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Мини-веб сервер успешно запущен на порту {port}")

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            tg_username TEXT,
            custom_nickname TEXT UNIQUE,
            is_moderator INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_posts (
            message_id INTEGER PRIMARY KEY,
            author_nickname TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_likes (
            message_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (message_id, user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS post_dislikes (
            message_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (message_id, user_id)
        )
    """)
    conn.commit()
    conn.close()

def is_user_registered(user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT custom_nickname FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None and res[0] is not None

def is_nickname_taken(nickname):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE LOWER(custom_nickname) = LOWER(?)", (nickname,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

def register_user(user_id, tg_username, nickname):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, tg_username, custom_nickname) 
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET tg_username=?, custom_nickname=?
    """, (user_id, tg_username, nickname, tg_username, nickname))
    conn.commit()
    conn.close()

def get_user_profile(user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT custom_nickname, is_moderator, is_vip, xp, level FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {"nickname": res[0], "is_moderator": res[1], "is_vip": res[2], "xp": res[3], "level": res[4]}
    return None

def get_profile_by_nickname(nickname):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, is_moderator, is_vip, xp, level FROM users WHERE LOWER(custom_nickname) = LOWER(?)", (nickname,))
    res = cursor.fetchone()
    conn.close()
    if res:
        return {"user_id": res[0], "nickname": nickname, "is_moderator": res[1], "is_vip": res[2], "xp": res[3], "level": res[4]}
    return None

def get_user_rank(user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rank FROM (
            SELECT user_id, RANK() OVER (ORDER BY level DESC, xp DESC) as rank FROM users WHERE custom_nickname IS NOT NULL
        ) WHERE user_id = ?
    """, (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else "Не определен"

def update_user_status(user_id, field, value):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def add_xp_by_nickname(nickname, amount):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, xp FROM users WHERE LOWER(custom_nickname) = LOWER(?)", (nickname,))
    res = cursor.fetchone()
    if res:
        user_id, current_xp = res[0], res[1]
        new_xp = max(0, current_xp + amount)
        new_level = (new_xp // 10) + 1
        cursor.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (new_xp, new_level, user_id))
        conn.commit()
    conn.close()

def save_channel_post(message_id, nickname):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO channel_posts (message_id, author_nickname) VALUES (?, ?)", (message_id, nickname))
    conn.commit()
    conn.close()

def get_author_by_post(message_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT author_nickname FROM channel_posts WHERE message_id = ?", (message_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def get_leaderboard():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT custom_nickname, level, xp FROM users WHERE custom_nickname IS NOT NULL ORDER BY level DESC, xp DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    return rows

def toggle_like(message_id, user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM post_dislikes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    cursor.execute("SELECT 1 FROM post_likes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    exists = cursor.fetchone()
    if exists:
        cursor.execute("DELETE FROM post_likes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
        change = -1
    else:
        cursor.execute("INSERT INTO post_likes (message_id, user_id) VALUES (?, ?)", (message_id, user_id))
        change = 1
    cursor.execute("SELECT COUNT(*) FROM post_likes WHERE message_id = ?", (message_id,))
    total_likes = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM post_dislikes WHERE message_id = ?", (message_id,))
    total_dislikes = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return change, total_likes, total_dislikes

def toggle_dislike(message_id, user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM post_likes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    had_like = cursor.fetchone() is not None
    if had_like:
        cursor.execute("DELETE FROM post_likes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    cursor.execute("SELECT 1 FROM post_dislikes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    exists = cursor.fetchone()
    if exists:
        cursor.execute("DELETE FROM post_dislikes WHERE message_id = ? AND user_id = ?", (message_id, user_id))
    else:
        cursor.execute("INSERT INTO post_dislikes (message_id, user_id) VALUES (?, ?)", (message_id, user_id))
    cursor.execute("SELECT COUNT(*) FROM post_likes WHERE message_id = ?", (message_id,))
    total_likes = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM post_dislikes WHERE message_id = ?", (message_id,))
    total_dislikes = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return had_like, total_likes, total_dislikes

# --- СОСТОЯНИЯ FSM ---
class RegStates(StatesGroup):
    waiting_for_nickname = State()

class StoryStates(StatesGroup):
    waiting_for_content = State()
    waiting_for_privacy = State()

# --- ГЛАВНОЕ МЕНЮ ---
async def send_main_menu(message_or_callback, user_id):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT xp FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if res:
        current_xp = res[0]
        calculated_level = (current_xp // 10) + 1
        cursor.execute("UPDATE users SET level = ? WHERE user_id = ?", (calculated_level, user_id))
        conn.commit()
    conn.close()

    profile = get_user_profile(user_id)
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Отправить историю", callback_data="start_story")
    builder.button(text="💎 Магазин привилегий", callback_data="open_shop")
    builder.button(text="🏆 Таблица Лидеров", callback_data="open_leaderboard")
    builder.adjust(1)

    text = (
        f"👋 **Привет, {profile['nickname']}! Рады видеть в ПОДСЛУШАНО!**\n\n"
        f"🏅 Твой уровень: `{profile['level']}` ({profile['xp']} XP)\n"
        f"👑 VIP-статус: {'✅ Активен (Доступен МУЛЬТИМЕДИА режим! 🔥)' if profile['is_vip'] else '❌ Не куплен (Только обычный текст)'}\n"
        f"⭐ Модератор: {'✅ Активен' if profile['is_moderator'] else '❌ Не куплен'}\n\n"
        f"Выбирай действие в меню ниже 👇"
    )
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await message_or_callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# --- СТАРТ И РЕГИСТРАЦИЯ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if is_user_registered(message.from_user.id):
        await send_main_menu(message, message.from_user.id)
    else:
        await message.answer(
            "👋 **Здравствуйте! Добро пожаловать в проект «ПОДСЛУШАНО»!**\n\n"
            "Придумай и **напиши мне свой уникальный никнейм** для регистрации:"
        )
        await state.set_state(RegStates.waiting_for_nickname)

@dp.message(RegStates.waiting_for_nickname, F.text & (F.chat.type == "private"))
async def process_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 3 or len(nickname) > 20 or "@" in nickname or "/" in nickname:
        await message.answer("❌ Длина от 3 до 20 символов, без знаков @ и /. Напиши другой:")
        return
    if is_nickname_taken(nickname):
        await message.answer("😢 Этот никнейм уже занят! Придумай другой:")
        return

    register_user(message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "Нет", nickname)
    await message.answer(f"🎉 Никнейм **{nickname}** успешно закреплен!")
    await state.clear()
    await send_main_menu(message, message.from_user.id)

# --- ПРОСМОТР ПРОФИЛЯ АВТОРА ИЗ КАНАЛА ---
@dp.callback_query(F.data.startswith("viewprof_"))
async def channel_view_profile(callback: types.CallbackQuery):
    target_nick = callback.data.replace("viewprof_", "")
    prof = get_profile_by_nickname(target_nick)
    if not prof:
        await callback.answer("❌ Профиль этого автора не найден.", show_alert=True)
        return
    rank = get_user_rank(prof["user_id"])
    vip_text = "👑 Да (VIP-Пользователь)" if prof["is_vip"] else "❌ Нет"
    mod_text = "⭐ Да (Модератор)" if prof["is_moderator"] else "❌ Нет"
    profile_card = (
        f"👤 **АНКЕТА АВТОРА:** `{prof['nickname']}`\n\n"
        f"📊 Место в общем Топе: **#{rank}**\n"
        f"🏅 Уровень автора: `{prof['level']}`\n"
        f"✨ Опыт автора: `{prof['xp']} XP`\n"
        f"💎 VIP-статус: {vip_text}\n"
        f"💼 Модератор: {mod_text}"
    )
    try:
        await bot.send_message(chat_id=callback.from_user.id, text=profile_card, parse_mode="Markdown")
        await callback.answer(f"📋 Анкета автора {target_nick} отправлена тебе в ЛС!", show_alert=False)
    except Exception:
        await callback.answer("⚠️ Чтобы увидеть профиль, сначала перейди в бота и нажми /start!", show_alert=True)

# --- МАГАЗИН STARS ---
@dp.callback_query(F.data == "open_shop")
async def open_shop(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="👑 Купить VIP статус (50 ⭐)", callback_data="buy_vip_stars")
    builder.button(text="⭐ Купить Модератора (300 ⭐)", callback_data="buy_moder_stars")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    await callback.message.edit_text(
        "🏪 **Магазин проектов Подслушано**\n\n"
        "• **VIP статус (50 ⭐):** Выделение постов короной + быстрая проверка + **СВОБОДА ОТПРАВКИ** (Картинки, Стикеры, Голосовые, Видео)!\n"
        "• **Модератор (300 ⭐):** Полный доступ в закрытый админ-чат модерации.",
        reply_markup=builder.as_markup(), parse_mode="Markdown"
    )

@dp.callback_query(F.data == "buy_vip_stars")
async def send_vip_invoice(callback: types.CallbackQuery):
    await callback.message.answer_invoice(
        title="👑 VIP-Статус «Подслушано»",
        description="Разблокирует отправку стикеров/фото/видео, выделение короной и быструю модерацию.",
        payload="buy_vip_status_payload", provider_token="", currency="XTR",
        prices=[types.LabeledPrice(label="Покупка VIP", amount=50)]
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_moder_stars")
async def send_moder_invoice(callback: types.CallbackQuery):
    await callback.message.answer_invoice(
        title="⭐ Роль Модератора «Подслушано»",
        description="Доступ в админ-чат модерации.",
        payload="buy_moder_status_payload", provider_token="", currency="XTR",
        prices=[types.LabeledPrice(label="Покупка Модерки", amount=300)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id
    if payload == "buy_vip_status_payload":
        update_user_status(user_id, "is_vip", 1)
        await message.answer("👑 **Оплата прошла успешно!** VIP-статус активирован! Перезапустите меню через /start.")
    elif payload == "buy_moder_status_payload":
        update_user_status(user_id, "is_moderator", 1)
        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=MODERATION_CHAT_ID,
                member_limit=1,
                name=f"Модератор: {message.from_user.full_name}"
            )
            builder = InlineKeyboardBuilder()
            builder.button(text="📥 Вступить в чат модерации", url=invite_link.invite_link)
            await message.answer(
                "⭐ **Оплата прошла успешно!** Роль Модератора выдана!\n\n"
                "Жми на кнопку ниже, чтобы вступить в закрытый рабочий чат:",
                reply_markup=builder.as_markup()
            )
        except Exception as e:
            logging.error(f"Ошибка создания ссылки в чат: {e}")
            await message.answer("⭐ **Оплата прошла успешно!** Роль Модератора выдана! Обратись к админу за ссылкой.")

# --- ТАБЛИЦА ЛИДЕРОВ ---
@dp.callback_query(F.data == "open_leaderboard")
async def show_leaderboard(callback: types.CallbackQuery):
    leaders = get_leaderboard()
    text = "🏆 **ТАБЛИЦА ЛИДЕРОВ (ТОП-10)**\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, user in enumerate(leaders):
        prefix = medals[i] if i < 3 else f"*{i+1}.*"
        text += f"{prefix} `{user[0]}` — `{user[1]} Уровень` ({user[2]} XP)\n"
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await send_main_menu(callback, callback.from_user.id)

# --- ПРИЕМ ИСТОРИЙ ---
@dp.callback_query(F.data == "start_story")
async def start_story(callback: types.CallbackQuery, state: FSMContext):
    if not is_user_registered(callback.from_user.id):
        await callback.answer("Сначала зарегистрируйся через /start!", show_alert=True)
        return
    profile = get_user_profile(callback.from_user.id)
    if profile["is_vip"]:
        await callback.message.answer("🌟 **VIP-режим активен!**\nОтправь мне свою историю. Можешь слать: Текст, Фото, Стикеры, Video или Голосовые!\n\n⚠️ *Отправка файлов заблокирована.*")
    else:
        await callback.message.answer("📝 **Обычный режим:**\nНапиши и отправь мне текст своей истории.\n\n⚠️ _Стикеры, картинки, video и голосовые доступны только для VIP-персон!_")
    await state.set_state(StoryStates.waiting_for_content)

@dp.message(StoryStates.waiting_for_content, F.chat.type == "private")
async def process_story_content(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)

    if message.text and message.text.strip() == SECRET_ADMIN_CODE:
        update_user_status(user_id, "is_vip", 1)
        update_user_status(user_id, "is_moderator", 1)
        await message.answer("🎁 **Секретный код активирован!** Выданы VIP и Модератор.")
        await state.clear()
        await send_main_menu(message, user_id)
        return

    if message.document:
        await message.answer("❌ **Отправка файлов запрещена!**")
        return

    if not profile["is_vip"] and not message.text:
        await message.answer("❌ **Обычные пользователи могут отправлять только чистый текст!**")
        return

    content_type = "text"
    file_id = None
    caption = ""
    reply_text = ""

    if message.text:
        caption = message.text
        reply_text = "📝 Текст истории успешно записан!"
    elif message.photo:
        content_type = "photo"
        file_id = message.photo[-1].file_id
        caption = message.caption if message.caption else ""
        reply_text = "📸 Фотография успешно принята!"
    elif message.sticker:
        content_type = "sticker"
        file_id = message.sticker.file_id
        reply_text = "🎯 Стикер успешно принят!"
    elif message.voice:
        content_type = "voice"
        file_id = message.voice.file_id
        caption = message.caption if message.caption else ""
        reply_text = "🎤 Голосовое сообщение записано!"
    elif message.video:
        content_type = "video"
        file_id = message.video.file_id
        caption = message.caption if message.caption else ""
        reply_text = "📹 Видео успешно загружено!"
    else:
        await message.answer("❌ Этот тип сообщения не поддерживается.")
        return

    await state.update_data(story_text=caption, file_id=file_id, content_type=content_type)
    builder = InlineKeyboardBuilder()
    builder.button(text="🥷 Анонимно", callback_data=f"anon___{profile['nickname']}")
    builder.button(text=f"📝 Под ником ({profile['nickname']})", callback_data=f"pub___{profile['nickname']}")
    await message.answer(f"{reply_text}\n\nВыбери формат публикации истории:", reply_markup=builder.as_markup())
    await state.set_state(StoryStates.waiting_for_privacy)

@dp.callback_query(StoryStates.waiting_for_privacy, F.data.startswith("anon") | F.data.startswith("pub"))
async def process_privacy_choice(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    story_text = user_data.get("story_text")
    file_id = user_data.get("file_id")
    content_type = user_data.get("content_type")
    
    user = callback.from_user
    profile = get_user_profile(user.id)
    vip_prefix = "👑 [VIP] " if profile["is_vip"] == 1 else ""
    tg_username = f"@{user.username}" if user.username else "Нет"
    user_info = (
        f"👤 **ТГ:** [{user.full_name}](tg://user?id={user.id}) ({tg_username})\n"
        f"🆔 **Ник в БД:** {vip_prefix}`{profile['nickname']}`"
    )
    if "anon" in callback.data:
        privacy_status = "🥷 **АНОНИМНО**"
        approve_callback = f"ap_an___{profile['nickname']}"
    else:
        privacy_status = f"📝 **Публично как {profile['nickname']}**"
        approve_callback = f"ap_pb___{profile['nickname']}"
        
    await callback.message.edit_text("📥 Отправлено модераторам на проверку!")
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Опубликовать", callback_data=approve_callback)
    builder.button(text="❌ Отклонить", callback_data="rej_post")
    
    moderation_text = (
        f"{user_info}\n"
        f"🔒 **Тип:** {privacy_status} (Уровень: `{profile['level']}`)\n"
        f"-----------------------------------\n\n"
        f"{story_text if story_text else '[Без текста]'}"
    )
    
    if content_type == "text":
        await bot.send_message(chat_id=MODERATION_CHAT_ID, text=moderation_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    elif content_type == "photo":
        await bot.send_photo(chat_id=MODERATION_CHAT_ID, photo=file_id, caption=moderation_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    elif content_type == "sticker":
        sticker_msg = await bot.send_sticker(chat_id=MODERATION_CHAT_ID, sticker=file_id)
        await bot.send_message(chat_id=MODERATION_CHAT_ID, text=moderation_text, reply_to_message_id=sticker_msg.message_id, reply_markup=builder.as_markup(), parse_mode="Markdown")
    elif content_type == "voice":
        await bot.send_voice(chat_id=MODERATION_CHAT_ID, voice=file_id, caption=moderation_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    elif content_type == "video":
        await bot.send_video(chat_id=MODERATION_CHAT_ID, video=file_id, caption=moderation_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await state.clear()

def get_channel_keyboard(message_id, likes=0, dislikes=0, nickname=None):
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data="like_click")
    builder.button(text=f"👎 {dislikes}", callback_data="dislike_click")
    builder.button(text="💬 Комменты", url=f"https://t.me/{CHANNEL_USERNAME}/{message_id}?comment=1")
    builder.adjust(3)
    if nickname:
        builder.row(types.InlineKeyboardButton(text=f"👤 Профиль автора: {nickname}", callback_data=f"viewprof_{nickname}"))
    return builder.as_markup()

# --- МОДЕРАЦИЯ (С ИМЕНЕМ МОДЕРАТОРА) ---
@dp.callback_query(F.data.startswith("ap_"))
async def process_moderation_approve(callback: types.CallbackQuery):
    if callback.message.chat.id != MODERATION_CHAT_ID:
        return
    action = callback.data
    original_text = callback.message.caption if callback.message.caption else callback.message.text
    if not original_text and callback.message.reply_to_message:
        original_text = callback.message.text
    try:
        story_content = original_text.split("-------------------\n\n")[1]
    except (IndexError, AttributeError):
        story_content = "[Медиафайл]" if not callback.message.caption else callback.message.caption

    # Получаем никнейм модератора, который нажал кнопку
    mod_user = callback.from_user
    mod_name = f"@{mod_user.username}" if mod_user.username else mod_user.full_name

    vip_emoji = ""
    nickname_for_db = action.split("___")[1]
    prof = get_profile_by_nickname(nickname_for_db)
    if prof and prof["is_vip"] == 1:
        vip_emoji = "👑 "

    photo_id = callback.message.photo[-1].file_id if callback.message.photo else None
    voice_id = callback.message.voice.file_id if callback.message.voice else None
    video_id = callback.message.video.file_id if callback.message.video else None
    sticker_id = callback.message.reply_to_message.sticker.file_id if (callback.message.reply_to_message and callback.message.reply_to_message.sticker) else None

    out_msg = None
    if action.startswith("ap_an"):
        clean_text = story_content if story_content != "[Медиафайл]" else ""
        final_caption = f"{vip_emoji}{clean_text}"
        fake_kb = get_channel_keyboard(0, 0, 0)
        
        if photo_id:
            out_msg = await bot.send_photo(chat_id=TARGET_CHANNEL_ID, photo=photo_id, caption=final_caption, reply_markup=fake_kb)
        elif voice_id:
            out_msg = await bot.send_voice(chat_id=TARGET_CHANNEL_ID, voice=voice_id, caption=final_caption, reply_markup=fake_kb)
        elif video_id:
            out_msg = await bot.send_video(chat_id=TARGET_CHANNEL_ID, video=video_id, caption=final_caption, reply_markup=fake_kb)
        elif sticker_id:
            await bot.send_sticker(chat_id=TARGET_CHANNEL_ID, sticker=sticker_id)
            out_msg = await bot.send_message(chat_id=TARGET_CHANNEL_ID, text=f"🎯 Свежий стикер от анонима!", reply_markup=fake_kb)
        else:
            out_msg = await bot.send_message(chat_id=TARGET_CHANNEL_ID, text=final_caption, reply_markup=fake_kb)
            
        if out_msg:
            await bot.edit_message_reply_markup(chat_id=TARGET_CHANNEL_ID, message_id=out_msg.message_id, reply_markup=get_channel_keyboard(out_msg.message_id, 0, 0))
            save_channel_post(out_msg.message_id, nickname_for_db)
        
        # Лог для админ-чата
        text_log = f"🟢 Опубликовано анонимно!\n📋 Модератор: {mod_name}\n\n{clean_text}"

    elif action.startswith("ap_pb"):
        vip_status_text = "✨ VIP-Автор" if vip_emoji else "Автор"
        clean_text = story_content if story_content != "[Медиафайл]" else ""
        
        # Текст поста с указанием модератора, принявшего пост
        if clean_text:
            public_text = f"{vip_emoji}{clean_text}\n\n✍️ **{vip_status_text}:** `{nickname_for_db}`\n📋 **Модератор:** {mod_name}"
        else:
            public_text = f"✍️ **{vip_status_text}:** `{nickname_for_db}`\n📋 **Модератор:** {mod_name}"
            
        fake_kb = get_channel_keyboard(0, 0, 0, nickname_for_db)
        
        if photo_id:
            out_msg = await bot.send_photo(chat_id=TARGET_CHANNEL_ID, photo=photo_id, caption=public_text, reply_markup=fake_kb, parse_mode="Markdown")
        elif voice_id:
            out_msg = await bot.send_voice(chat_id=TARGET_CHANNEL_ID, voice=voice_id, caption=public_text, reply_markup=fake_kb, parse_mode="Markdown")
        elif video_id:
            out_msg = await bot.send_video(chat_id=TARGET_CHANNEL_ID, video=video_id, caption=public_text, reply_markup=fake_kb, parse_mode="Markdown")
        elif sticker_id:
            await bot.send_sticker(chat_id=TARGET_CHANNEL_ID, sticker=sticker_id)
            out_msg = await bot.send_message(chat_id=TARGET_CHANNEL_ID, text=public_text, reply_markup=fake_kb, parse_mode="Markdown")
        else:
            out_msg = await bot.send_message(chat_id=TARGET_CHANNEL_ID, text=public_text, reply_markup=fake_kb, parse_mode="Markdown")
            
        if out_msg:
            await bot.edit_message_reply_markup(chat_id=TARGET_CHANNEL_ID, message_id=out_msg.message_id, reply_markup=get_channel_keyboard(out_msg.message_id, 0, 0, nickname_for_db))
            save_channel_post(out_msg.message_id, nickname_for_db)
            
        # Лог для админ-чата
        text_log = f"🟢 Опубликовано под ником {nickname_for_db}!\n📋 Модератор: {mod_name}\n\n{clean_text}"

    try:
        if callback.message.photo or callback.message.voice or callback.message.video:
            await callback.message.edit_caption(caption=text_log)
        else:
            await callback.message.edit_text(text=text_log)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "rej_post")
async def process_moderation_reject(callback: types.CallbackQuery):
    if callback.message.chat.id != MODERATION_CHAT_ID:
        return
    
    # Получаем никнейм модератора, отклонившего пост
    mod_user = callback.from_user
    mod_name = f"@{mod_user.username}" if mod_user.username else mod_user.full_name
    
    try:
        if callback.message.photo or callback.message.voice or callback.message.video:
            await callback.message.edit_caption(caption=f"🔴 Отклонено модератором: {mod_name}")
        else:
            await callback.message.edit_text(text=f"🔴 Отклонено модератором: {mod_name}")
    except Exception:
        pass
    await callback.answer("Пост успешно отклонен!")

# --- ОБРАБОТКА ЛАЙКОВ ---
@dp.callback_query(F.data == "like_click")
async def process_like_click(callback: types.CallbackQuery):
    message_id = callback.message.message_id
    user_id = callback.from_user.id
    author_nickname = get_author_by_post(message_id)
    if not author_nickname:
        await callback.answer("⚠️ Ошибка: Автор поста не найден в БД.", show_alert=True)
        return
    change, total_likes, total_dislikes = toggle_like(message_id, user_id)
    add_xp_by_nickname(author_nickname, change)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_channel_keyboard(message_id, total_likes, total_dislikes, author_nickname))
        if change == 1:
            await callback.answer("❤️ Вы поставили лайк! Автору начислено +1 XP.")
        else:
            await callback.answer("💔 Вы убрали лайк. У автора списано 1 XP.")
    except Exception:
        await callback.answer()

# --- ОБРАБОТКА ДИЗЛАЙКОВ ---
@dp.callback_query(F.data == "dislike_click")
async def process_dislike_click(callback: types.CallbackQuery):
    message_id = callback.message.message_id
    user_id = callback.from_user.id
    author_nickname = get_author_by_post(message_id)
    if not author_nickname:
        await callback.answer("⚠️ Ошибка: Автор поста не найден в БД.", show_alert=True)
        return
    had_like, total_likes, total_dislikes = toggle_dislike(message_id, user_id)
    if had_like:
        add_xp_by_nickname(author_nickname, -1)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_channel_keyboard(message_id, total_likes, total_dislikes, author_nickname))
        await callback.answer("👎 Вы поставили дизлайк! (На рейтинг и XP автора это не влияет)")
    except Exception:
        await callback.answer()

# --- ЗАПУСК БОТА ---
async def main():
    init_db()
    asyncio.create_task(start_webhook_server())
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    asyncio.run(main())
