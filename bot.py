"""
Groq + PPTX Telegram bot
========================
Foydalanuvchi:
  1) Mavzu asosida to'liq PowerPoint prezentatsiya (matn + grafik + flowchart + orgchart)
     yaratishi mumkin, YOKI
  2) Faqat bitta diagramma (pie/bar/line/flowchart/orgchart/venn/timeline) yaratishi mumkin.

Ishga tushirish:
    python bot.py
(oldin .env faylini to'ldiring — .env.example ga qarang)
"""
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

from datetime import datetime

from config import TELEGRAM_BOT_TOKEN, DB_CHANNEL_ID
import groq_client
import pptx_builder
import slide_renderer
import access_control as ac

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Conversation holatlari
# --------------------------------------------------------------------------
(
    CHOOSING_MODE,
    PRESO_TOPIC,
    PRESO_SLIDES,
    DIAGRAM_TYPE,
    DIAGRAM_DESC,
) = range(5)

DIAGRAM_LABELS = {
    "pie": "🥧 Doiraviy (Pie)",
    "bar": "📊 Ustunli (Bar)",
    "line": "📈 Chiziqli (Line)",
    "flowchart": "🔀 Jarayon (Flowchart)",
    "orgchart": "🏢 Tuzilma (Org chart)",
    "venn": "⭕ Venn diagramma",
    "timeline": "🕒 Vaqt chizig'i (Timeline)",
    "auto": "🤖 AI o'zi tanlasin",
}


# --------------------------------------------------------------------------
# "DB kanal" — har bir so'rov va yaratilgan fayl shu (xususiy) kanalga log
# sifatida yuboriladi. Haqiqiy database o'rniga oddiy va ishonchli yechim:
# Telegram kanali cheksizga yaqin xabar/fayl saqlaydi va istalgan vaqt qidirish/
# filtrlash imkonini beradi. Botni kanalga ADMIN qilib qo'shish kifoya.
# --------------------------------------------------------------------------

async def log_to_db_channel(context: ContextTypes.DEFAULT_TYPE, update: Update,
                             filepath: str, kind: str, request_text: str) -> None:
    if not DB_CHANNEL_ID:
        return

    user = update.effective_user
    caption = (
        f"🗂 <b>{kind}</b>\n"
        f"👤 {user.full_name} (@{user.username or '—'}, id: {user.id})\n"
        f"📝 So'rov: {request_text}\n"
        f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    try:
        with open(filepath, "rb") as f:
            await context.bot.send_document(
                chat_id=DB_CHANNEL_ID,
                document=f,
                filename=os.path.basename(filepath),
                caption=caption,
                parse_mode="HTML",
            )
    except Exception:  # noqa: BLE001 - log yozilmasa ham foydalanuvchi oqimi buzilmasin
        logger.exception("DB kanalga yozishda xatolik (chat_id=%s)", DB_CHANNEL_ID)


# --------------------------------------------------------------------------
# "Slaydlarni rasm sifatida ko'rish" — inline tugma orqali chaqiriladi.
# Har bir slaydni alohida rasmga aylantirib, albom (media group) sifatida yuboradi.
# --------------------------------------------------------------------------

def _preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🖼 Slaydlarni rasm sifatida ko'rish", callback_data="preview_slides")
    ]])


async def preview_slides_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Slaydlar tayyorlanmoqda...")

    filepath = context.user_data.get("last_pptx_path")
    if not filepath or not os.path.exists(filepath):
        await context.bot.send_message(
            update.effective_chat.id,
            "⚠️ Fayl topilmadi (ehtimol eskirgan). Iltimos, /start orqali qayta yarating.",
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)

    try:
        image_paths = slide_renderer.render_slides_to_images(filepath)
    except slide_renderer.RenderError as e:
        await context.bot.send_message(update.effective_chat.id, f"❌ {e}")
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("Slaydlarni rasmga aylantirishda kutilmagan xato")
        await context.bot.send_message(update.effective_chat.id, f"❌ Kutilmagan xatolik: {e}")
        return

    # Telegram bitta media-group'da eng ko'p 10 ta rasm qabul qiladi — shu sabab guruhlarga bo'lamiz
    for i in range(0, len(image_paths), 10):
        chunk = image_paths[i:i + 10]
        opened_files = [open(p, "rb") for p in chunk]
        try:
            media = [InputMediaPhoto(f, caption=f"Slayd {i + idx + 1}" if idx == 0 and i == 0 else None)
                     for idx, f in enumerate(opened_files)]
            await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)
        finally:
            for f in opened_files:
                f.close()


# --------------------------------------------------------------------------
# Generatsiyadan oldin chaqiriladi — kunlik limitni tekshiradi va oshiradi.
# --------------------------------------------------------------------------

async def _check_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True — davom etish mumkin. False — rad etildi (xabar allaqachon yuborilgan)."""
    user = update.effective_user
    allowed, used, limit = ac.check_and_increment(user.id)

    if allowed:
        return True

    chat_id = update.effective_chat.id
    if limit == 0 and used == 0:
        await context.bot.send_message(
            chat_id,
            "🚫 Ruxsatingiz bekor qilingan yoki mavjud emas. Administrator bilan bog'laning.",
        )
    else:
        await context.bot.send_message(
            chat_id,
            f"⏳ Bugungi limitingiz tugadi ({used}/{limit}).\n"
            "Ertaga (kecha yarmidan keyin) qayta urinib ko'ring, yoki administratordan "
            "limitni oshirishni so'rang.",
        )
    return False


# --------------------------------------------------------------------------
# /start va asosiy menyu
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if not ac.is_whitelisted(user.id):
        await update.message.reply_text(
            "🚫 Kechirasiz, botdan foydalanish uchun ruxsatingiz yo'q.\n\n"
            f"Sizning ID'ingiz: <code>{user.id}</code>\n"
            "Buni administratorga yuborib, ruxsat so'rang.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📊 Prezentatsiya yaratish", callback_data="mode_preso")],
        [InlineKeyboardButton("📈 Diagramma yaratish", callback_data="mode_diagram")],
    ]
    text = (
        "Salom! 👋 Men Groq AI yordamida PowerPoint (.pptx) prezentatsiya va "
        "diagrammalar yarataman.\n\n"
        "Nima qilishni xohlaysiz?"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_MODE


async def mode_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "mode_preso":
        await query.edit_message_text(
            "Ajoyib! 📝 Prezentatsiya mavzusini yozib yuboring.\n\n"
            "Masalan: <i>\"Klimat o'zgarishi va uning oqibatlari\"</i>",
            parse_mode="HTML",
        )
        return PRESO_TOPIC

    elif query.data == "mode_diagram":
        keyboard = [
            [InlineKeyboardButton(label, callback_data=f"dtype_{key}")]
            for key, label in DIAGRAM_LABELS.items()
        ]
        await query.edit_message_text(
            "Qanday turdagi diagramma kerak?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return DIAGRAM_TYPE

    return CHOOSING_MODE


# --------------------------------------------------------------------------
# 1) TO'LIQ PREZENTATSIYA OQIMI
# --------------------------------------------------------------------------

async def preso_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["topic"] = update.message.text.strip()

    keyboard = [
        [
            InlineKeyboardButton("3", callback_data="n_3"),
            InlineKeyboardButton("5", callback_data="n_5"),
            InlineKeyboardButton("7", callback_data="n_7"),
            InlineKeyboardButton("10", callback_data="n_10"),
        ]
    ]
    await update.message.reply_text(
        "Nechta slayd bo'lsin? (title slaydidan tashqari)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return PRESO_SLIDES


async def preso_slides_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    num_slides = int(query.data.split("_")[1])
    topic = context.user_data.get("topic", "Noma'lum mavzu")

    if not await _check_limit(update, context):
        return ConversationHandler.END

    await query.edit_message_text(
        f"⏳ \"{topic}\" mavzusida {num_slides} slaydli prezentatsiya tayyorlanmoqda...\n"
        f"Bu bir necha soniya vaqt olishi mumkin."
    )
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)

    try:
        data = groq_client.generate_presentation(topic, num_slides)
        filepath = pptx_builder.build_presentation_file(data)

        with open(filepath, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=os.path.basename(filepath),
                caption=f"✅ Tayyor! \"{data.get('title')}\" prezentatsiyasi.",
                reply_markup=_preview_keyboard(),
            )
        context.user_data["last_pptx_path"] = filepath

        await log_to_db_channel(context, update, filepath, "Prezentatsiya", f"{topic} ({num_slides} slayd)")
    except groq_client.GroqGenerationError as e:
        logger.exception("Groq xatosi")
        await context.bot.send_message(update.effective_chat.id, f"❌ Xatolik yuz berdi: {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception("Kutilmagan xato")
        await context.bot.send_message(update.effective_chat.id, f"❌ Kutilmagan xatolik: {e}")

    await context.bot.send_message(
        update.effective_chat.id,
        "Yana nimadir yaratmoqchimisiz? /start bosing.",
    )
    return ConversationHandler.END


# --------------------------------------------------------------------------
# 2) FAQAT DIAGRAMMA OQIMI
# --------------------------------------------------------------------------

async def diagram_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    dtype = query.data.replace("dtype_", "")
    context.user_data["diagram_hint"] = "" if dtype == "auto" else dtype

    label = DIAGRAM_LABELS.get(dtype, dtype)
    await query.edit_message_text(
        f"Tanlandi: {label}\n\n"
        "Endi diagramma mazmunini tavsiflab bering.\n\n"
        "Masalan: <i>\"Kompaniyamiz bo'limlari: Sotuv 40%, Marketing 25%, "
        "IT 20%, Moliya 15%\"</i> yoki <i>\"Mahsulot yaratish bosqichlari: "
        "g'oya, dizayn, dasturlash, test, chiqarish\"</i>",
        parse_mode="HTML",
    )
    return DIAGRAM_DESC


async def diagram_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text.strip()
    hint = context.user_data.get("diagram_hint", "")

    if not await _check_limit(update, context):
        return ConversationHandler.END

    await update.message.reply_text("⏳ Diagramma tayyorlanmoqda...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)

    try:
        data = groq_client.generate_diagram_data(description, hint)
        filepath = pptx_builder.build_diagram_file(data)

        with open(filepath, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=os.path.basename(filepath),
                caption=f"✅ Tayyor! \"{data.get('title')}\" diagrammasi.",
                reply_markup=_preview_keyboard(),
            )
        context.user_data["last_pptx_path"] = filepath

        await log_to_db_channel(context, update, filepath, "Diagramma", description)
    except groq_client.GroqGenerationError as e:
        logger.exception("Groq xatosi")
        await update.message.reply_text(f"❌ Xatolik yuz berdi: {e}")
    except Exception as e:  # noqa: BLE001
        logger.exception("Kutilmagan xato")
        await update.message.reply_text(f"❌ Kutilmagan xatolik: {e}")

    await update.message.reply_text("Yana nimadir yaratmoqchimisiz? /start bosing.")
    return ConversationHandler.END


# --------------------------------------------------------------------------
# Bekor qilish / yordam
# --------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Bekor qilindi. /start bilan qayta boshlashingiz mumkin.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "/start — botni boshlash\n"
        "/cancel — joriy amalni bekor qilish\n"
        "/help — yordam"
    )
    if ac.is_admin(update.effective_user.id):
        text += "\n\n🛠 Siz administratorsiz — /admin buyrug'i orqali whitelist'ni boshqarishingiz mumkin."
    await update.message.reply_text(text)


# --------------------------------------------------------------------------
# ADMIN PANEL — faqat config.ADMIN_USER_IDS'dagi foydalanuvchilar uchun.
# Whitelist'ni shu buyruqlar orqali boshqarasiz.
# --------------------------------------------------------------------------

def _parse_limit(text: str):
    """'5' -> 5, 'infinity'/'inf'/'cheksiz' -> None. Noto'g'ri bo'lsa ValueError."""
    text = text.strip().lower()
    if text in ("infinity", "inf", "cheksiz", "unlimited", "-1"):
        return None
    return int(text)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not ac.is_admin(user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return

    await update.message.reply_text(
        "🛠 <b>Admin panel</b>\n\n"
        "/adduser <code>user_id limit</code> — foydalanuvchi qo'shish/yangilash\n"
        "   masalan: <code>/adduser 123456789 5</code> (kuniga 5 marta)\n"
        "   yoki: <code>/adduser 123456789 infinity</code> (cheksiz)\n\n"
        "/removeuser <code>user_id</code> — whitelist'dan o'chirish\n\n"
        "/setlimit <code>user_id limit</code> — limitni o'zgartirish "
        "(<code>/adduser</code> bilan bir xil)\n\n"
        "/listusers — whitelist'dagi barcha foydalanuvchilar va bugungi "
        "foydalanishlari\n\n"
        "ℹ️ Foydalanuvchi ID'ini bilish uchun ular sizga o'z ID'sini yuboradi "
        "(botdan ruxsatsiz foydalanishga urinishganda bot avtomatik ko'rsatadi).",
        parse_mode="HTML",
    )


async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ac.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Foydalanish: /adduser <user_id> <limit>\n"
            "Masalan: /adduser 123456789 5  yoki  /adduser 123456789 infinity"
        )
        return

    try:
        target_id = int(context.args[0])
        limit = _parse_limit(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ user_id butun son, limit esa son yoki 'infinity' bo'lishi kerak.")
        return

    ac.add_user(target_id, limit)
    limit_text = "cheksiz" if limit is None else str(limit)
    await update.message.reply_text(f"✅ Foydalanuvchi {target_id} qo'shildi/yangilandi. Kunlik limit: {limit_text}.")


async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ac.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return

    if not context.args:
        await update.message.reply_text("Foydalanish: /removeuser <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id butun son bo'lishi kerak.")
        return

    removed = ac.remove_user(target_id)
    if removed:
        await update.message.reply_text(f"✅ Foydalanuvchi {target_id} whitelist'dan o'chirildi.")
    else:
        await update.message.reply_text(f"⚠️ Foydalanuvchi {target_id} whitelist'da topilmadi.")


async def set_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /setlimit — /adduser bilan bir xil ishlaydi (upsert)
    await add_user_command(update, context)


async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ac.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return

    users = ac.list_users()
    lines = [f"👑 <b>Adminlar:</b> {', '.join(str(a) for a in ac.ADMIN_USER_IDS) or '—'} (cheksiz)\n"]

    if not users:
        lines.append("Whitelist bo'sh.")
    else:
        lines.append(f"📋 <b>Whitelist ({len(users)} ta):</b>")
        for user_id, username, limit, added_at, used in users:
            limit_text = "∞" if limit is None else str(limit)
            uname = f"@{username}" if username else ""
            lines.append(f"• <code>{user_id}</code> {uname} — bugun: {used}/{limit_text}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN topilmadi. .env faylini to'ldiring.")

    ac.init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_MODE: [CallbackQueryHandler(mode_chosen, pattern="^mode_")],
            PRESO_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, preso_topic_received)],
            PRESO_SLIDES: [CallbackQueryHandler(preso_slides_received, pattern="^n_")],
            DIAGRAM_TYPE: [CallbackQueryHandler(diagram_type_chosen, pattern="^dtype_")],
            DIAGRAM_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, diagram_desc_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(preview_slides_callback, pattern="^preview_slides$"))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("adduser", add_user_command))
    app.add_handler(CommandHandler("removeuser", remove_user_command))
    app.add_handler(CommandHandler("setlimit", set_limit_command))
    app.add_handler(CommandHandler("listusers", list_users_command))

    # --------------------------------------------------------------------
    # Ishga tushirish rejimini avtomatik aniqlash:
    #  - Render'da RENDER_EXTERNAL_URL muhit o'zgaruvchisi avtomatik mavjud
    #    bo'ladi -> WEBHOOK rejimida ishga tushiramiz (bepul Web Service
    #    tashqi HTTP so'rov qabul qilishi kerak).
    #  - Lokal kompyuterda (Windows va h.k.) bu o'zgaruvchi yo'q -> oddiy
    #    POLLING rejimida ishga tushamiz (hech narsa o'zgartirish shart emas).
    # --------------------------------------------------------------------
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()

    if render_url:
        port = int(os.getenv("PORT", "10000"))
        # Tokenni webhook manzilining "maxfiy" qismi sifatida ishlatamiz —
        # shu tariqa faqat Telegram biladigan manzilga so'rov yuboradi.
        url_path = TELEGRAM_BOT_TOKEN
        webhook_url = f"{render_url.rstrip('/')}/{url_path}"

        logger.info("WEBHOOK rejimida ishga tushmoqda: %s (port=%s)", webhook_url, port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("POLLING rejimida ishga tushmoqda (lokal ishlash)...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
