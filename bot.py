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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

from datetime import datetime

from config import TELEGRAM_BOT_TOKEN, DB_CHANNEL_ID
import groq_client
import pptx_builder

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
# /start va asosiy menyu
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            )

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
            )

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
    await update.message.reply_text(
        "/start — botni boshlash\n"
        "/cancel — joriy amalni bekor qilish\n"
        "/help — yordam"
    )


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN topilmadi. .env faylini to'ldiring.")

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

    logger.info("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
