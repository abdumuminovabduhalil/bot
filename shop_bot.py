import json
import re
from pathlib import Path
from datetime import datetime
import os


from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- НАСТРОЙКИ ----------------
TOKEN = os.getenv("BOT_TOKEN")


# Куда слать заказы (твой user_id и/или id группы)
ADMIN_IDS = [6397487392]  # замени/добавь сюда админов
GROUP_CHAT_ID = -5137602691      # если хочешь группу: -1001234567890, иначе None

# Если хочешь ограничить только одним каналом, укажи его chat_id (обычно -100...).
# Если оставить пустым списком — будет принимать товары из любого канала, где бот админ.
ALLOWED_CHANNEL_IDS = []  # пример: [-1001112223334]

DATA_FILE = Path("products.json")

# ---------------- КАТЕГОРИИ ----------------
TAG_TO_CAT = {
    "#клава": "keyboards",
    "#клавиатура": "keyboards",
    "#мышь": "mice",
    "#монитор": "monitors",
    "#пк": "pc",
    "#компьютер": "pc",
}

CAT_NAME = {
    "keyboards": "⌨️ Клавиатуры",
    "mice": "🖱 Мыши",
    "monitors": "🖥 Мониторы",
    "pc": "💻 Компьютеры",
}

# products: dict[str, list[dict]]
# item: {id, name, price, photo_file_id, added_from_channel, created_at}
def load_products():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_products(products: dict):
    DATA_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")

PRODUCTS = load_products()

# ---------------- ВСПОМОГАТЕЛЬНОЕ ----------------
def get_dest_chats():
    chats = list(ADMIN_IDS)
    if isinstance(GROUP_CHAT_ID, int):
        chats.append(GROUP_CHAT_ID)
    return chats

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Заказать", callback_data="order")],
        [InlineKeyboardButton("🆕 Обновить меню", callback_data="refresh")],
    ])

def categories_menu():
    # показываем все категории (даже если пусто)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(CAT_NAME["keyboards"], callback_data="cat|keyboards")],
        [InlineKeyboardButton(CAT_NAME["mice"], callback_data="cat|mice")],
        [InlineKeyboardButton(CAT_NAME["monitors"], callback_data="cat|monitors")],
        [InlineKeyboardButton(CAT_NAME["pc"], callback_data="cat|pc")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_main")],
    ])

def products_menu(cat_key: str):
    items = PRODUCTS.get(cat_key, [])
    if not items:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="order")]])

    rows = []
    for p in items[:30]:  # чтобы меню не стало огромным
        rows.append([InlineKeyboardButton(f"{p['name']} — {p['price']}", callback_data=f"pick|{p['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="order")])
    return InlineKeyboardMarkup(rows)

def contact_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def find_product(pid: str):
    for cat, items in PRODUCTS.items():
        for p in items:
            if p["id"] == pid:
                return cat, p
    return None, None

def make_product_id(channel_id: int, message_id: int) -> str:
    return f"{channel_id}_{message_id}"

def parse_channel_post(text: str):
    """
    Возвращает (cat_key, name, price) или (None,None,None)
    Ожидаем:
    1 строка: #тег
    2 строка: Название
    где-то: Цена: ...
    """
    if not text:
        return None, None, None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, None, None

    tag = lines[0].lower()
    cat = TAG_TO_CAT.get(tag)
    if not cat:
        return None, None, None

    name = lines[1]

    m = re.search(r"цена\s*:\s*(.+)", text, flags=re.IGNORECASE)
    price = m.group(1).strip() if m else None
    if not price:
        return None, None, None

    return cat, name, price

# ---------------- КОМАНДЫ ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\nНажми «Заказать», чтобы выбрать товар.",
        reply_markup=main_menu()
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Твой chat_id: {update.effective_chat.id}")

# ---------------- КНОПКИ МАГАЗИНА ----------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ("refresh",):
        await query.edit_message_text("✅ Меню обновлено.", reply_markup=main_menu())
        return

    if data == "order":
        await query.edit_message_text("🛍 Выбери категорию:", reply_markup=categories_menu())
        return

    if data == "back_main":
        await query.edit_message_text("🏠 Главное меню:", reply_markup=main_menu())
        return

    if data.startswith("cat|"):
        cat_key = data.split("|", 1)[1]
        items = PRODUCTS.get(cat_key, [])
        if not items:
            await query.edit_message_text(
                f"{CAT_NAME.get(cat_key,'Категория')}\n\n❌ Пока пусто. Добавь товары в канал.",
                reply_markup=products_menu(cat_key)
            )
        else:
            await query.edit_message_text(
                f"{CAT_NAME.get(cat_key,'Категория')}\n\n✅ Выбери товар:",
                reply_markup=products_menu(cat_key)
            )
        return

    if data.startswith("pick|"):
        pid = data.split("|", 1)[1]
        cat_key, p = find_product(pid)
        if not p:
            await query.edit_message_text("❌ Товар не найден.", reply_markup=main_menu())
            return

        # ждём телефон
        context.user_data["waiting_phone"] = True
        context.user_data["selected_pid"] = pid

        pretty = (
            f"🧾 *Вы выбрали товар*\n"
            f"• Категория: {CAT_NAME.get(cat_key,'')}\n"
            f"• Товар: *{p['name']}*\n"
            f"• Цена: *{p['price']}*\n\n"
            "📱 Отправь номер кнопкой ниже или напиши номер сообщением (пример: +998901234567)."
        )

        # картинка товара (photo_file_id из канала)
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=p["photo_file_id"],
                caption=pretty,
                parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=pretty,
                parse_mode="Markdown"
            )

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="👇 Нажми кнопку, чтобы отправить номер:",
            reply_markup=contact_kb()
        )

        await query.edit_message_text("✅ Ок! Жду номер телефона…")
        return

    # админ принять/отклонить
    if data.startswith("adm_ok|") or data.startswith("adm_no|"):
        if not is_admin(query.from_user.id):
            await query.answer("⛔ Только админ может нажимать", show_alert=True)
            return

        action, user_id, pid = data.split("|", 2)
        user_id = int(user_id)
        cat_key, p = find_product(pid)

        if not p:
            await query.edit_message_text("❌ Товар не найден.")
            return

        if action == "adm_ok":
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Ваш заказ *принят*!\n\nТовар: *{p['name']}* — {p['price']}\nСкоро свяжемся 📞",
                parse_mode="Markdown"
            )
            await query.edit_message_text(f"✅ Принято.\n{p['name']} — {p['price']}\nuser_id: {user_id}")
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Ваш заказ *отклонён*.\n\nТовар: *{p['name']}* — {p['price']}\nПопробуйте позже 🙏",
                parse_mode="Markdown"
            )
            await query.edit_message_text(f"❌ Отклонено.\n{p['name']} — {p['price']}\nuser_id: {user_id}")
        return

# ---------------- ПОЛУЧЕНИЕ ТЕЛЕФОНА ----------------
async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_phone"):
        return
    phone = update.message.contact.phone_number if update.message.contact else None
    await finalize_order(update, context, phone)

async def on_phone_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_phone"):
        return
    phone = (update.message.text or "").strip()
    if len(phone) < 7:
        await update.message.reply_text("❗ Похоже это не номер. Напиши номер типа +998901234567")
        return
    await finalize_order(update, context, phone)

async def finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    pid = context.user_data.get("selected_pid")
    cat_key, p = find_product(pid)

    await update.message.reply_text("✅ Спасибо!", reply_markup=ReplyKeyboardRemove())

    if not p:
        await update.message.reply_text("❌ Ошибка: товар не найден.")
        context.user_data.clear()
        return

    user = update.effective_user
    username = f"@{user.username}" if user.username else "(без username)"

    text_for_admin = (
        "🧾 *НОВЫЙ ЗАКАЗ*\n"
        f"• Категория: {CAT_NAME.get(cat_key,'')}\n"
        f"• Товар: *{p['name']}*\n"
        f"• Цена: *{p['price']}*\n"
        f"• Телефон: `{phone}`\n"
        f"• От: {user.full_name} {username}\n"
        f"• user_id: `{user.id}`"
    )

    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"adm_ok|{user.id}|{p['id']}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_no|{user.id}|{p['id']}"),
        ]
    ])

    for chat_id in get_dest_chats():
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=p["photo_file_id"],
                caption=text_for_admin,
                parse_mode="Markdown",
                reply_markup=admin_kb
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text_for_admin,
                parse_mode="Markdown",
                reply_markup=admin_kb
            )

    await update.message.reply_text(
        "✅ Заказ отправлен продавцу!\nЖди подтверждения 😉",
        reply_markup=main_menu()
    )

    context.user_data.clear()

# ---------------- ПРИЁМ ТОВАРОВ ИЗ КАНАЛА ----------------
async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post
    if not post:
        return

    channel_id = post.chat.id
    if ALLOWED_CHANNEL_IDS and channel_id not in ALLOWED_CHANNEL_IDS:
        return

    # нужен текст и фото
    text = post.caption or post.text or ""
    cat_key, name, price = parse_channel_post(text)
    if not cat_key:
        return  # не по шаблону

    if not post.photo:
        return  # без картинки не добавляем

    # берём самое большое фото
    photo_file_id = post.photo[-1].file_id

    pid = make_product_id(channel_id, post.message_id)

    # не дублируем
    items = PRODUCTS.get(cat_key, [])
    if any(x.get("id") == pid for x in items):
        return

    item = {
        "id": pid,
        "name": name,
        "price": price,
        "photo_file_id": photo_file_id,
        "added_from_channel": channel_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    PRODUCTS.setdefault(cat_key, []).insert(0, item)
    save_products(PRODUCTS)

    # (по желанию) уведомить админов, что товар добавлен
    for chat_id in get_dest_chats():
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Товар добавлен из канала: {CAT_NAME.get(cat_key,'')}\n{name} — {price}"
            )
        except Exception:
            pass

# ---------------- ЗАПУСК ----------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))

    app.add_handler(CallbackQueryHandler(on_button))

    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_phone_text))

    # самое важное: ловим новые посты из канала
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, on_channel_post))

    app.run_polling()

if __name__ == "__main__":
    main()
