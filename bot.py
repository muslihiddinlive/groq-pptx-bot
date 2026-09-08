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
import asyncio
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, ApplicationHandlerStop,
)

from datetime import datetime

from config import TELEGRAM_BOT_TOKEN, DB_CHANNEL_ID, ADMIN_USER_IDS
import groq_client
import pptx_builder
import slide_renderer
import access_control as ac
import file_assistant

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _safe_answer(query, text: str = None) -> None:
    """query.answer()ni xavfsiz chaqiradi — agar callback query eskirib
    qolgan bo'lsa (masalan bot qayta ishga tushgandan keyin, yoki foydalanuvchi
    juda eski xabardagi tugmani bossa), Telegram 'Query is too old...' xatosini
    qaytaradi. Bu holatda botni yiqitmasdan, shunchaki e'tiborsiz qoldiramiz."""
    try:
        await query.answer(text=text) if text else await query.answer()
    except BadRequest as e:
        if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
            logger.info("Eskirgan callback query e'tiborsiz qoldirildi: %s", e)
        else:
            raise

# --------------------------------------------------------------------------
# Conversation holatlari
# --------------------------------------------------------------------------
(
    CHOOSING_MODE,
    PRESO_TOPIC,
    PRESO_SLIDES,
    DIAGRAM_TYPE,
    DIAGRAM_DESC,
    FILE_ASSISTANT,
) = range(6)

(
    ADMIN_MENU,
    ADMIN_WAIT_ADD,
    ADMIN_WAIT_REMOVE,
    ADMIN_WAIT_SETLIMIT,
) = range(6, 10)

# (admin_chat_id, admin_message_id) -> original_user_chat_id
# Admin forward qilingan xabarga "reply" qilsa, javob shu orqali foydalanuvchiga qaytadi.
# ESLATMA: xotirada saqlanadi — bot qayta ishga tushsa, eski xabarlarga reply ishlamay
# qoladi (yangi murojaatlar bilan qayta ishlay boshlaydi). Bu MVP uchun yetarli.
_relay_map: dict[tuple[int, int], int] = {}

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
        # subprocess.run (LibreOffice) va PDF->rasm konvertatsiyasi to'liq
        # bloklovchi amal — asyncio.to_thread orqali alohida oqimga chiqarilmasa,
        # shu vaqt ichida bot BOSHQA HECH KIMGA javob bera olmaydi ("qotib qoladi").
        image_paths = await asyncio.to_thread(slide_renderer.render_slides_to_images, filepath)
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
# "Adminga murojaat" — ruxsatsiz foydalanuvchi tugmani bosgach, keyingi
# xabari (matn/rasm/fayl — istalgani) avtomatik adminlarga forward qilinadi.
# Admin forward qilingan xabarga "reply" qilsa, javob foydalanuvchiga qaytadi.
# --------------------------------------------------------------------------

async def contact_admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _safe_answer(query)

    if not ADMIN_USER_IDS:
        await query.edit_message_text("⚠️ Hozircha admin sozlanmagan. Keyinroq urinib ko'ring.")
        return

    context.user_data["awaiting_admin_relay"] = True
    await query.edit_message_text(
        "✍️ Xabaringizni yozing — matn, rasm yoki fayl bo'lishi mumkin.\n"
        "Yuborgan zahotingiz adminga yetkazib beraman."
    )


async def relay_to_admin_or_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Whitelist'da bo'lmagan va aktiv conversation'da bo'lmagan foydalanuvchilardan
    kelgan har qanday xabarni ushlaydi. Agar 'adminga murojaat' rejimida bo'lsa —
    forward qiladi, aks holda /start bosishni so'raydi."""
    user = update.effective_user
    msg = update.message

    if not context.user_data.get("awaiting_admin_relay"):
        await msg.reply_text("Botdan foydalanish uchun /start buyrug'ini yuboring.")
        return

    context.user_data["awaiting_admin_relay"] = False

    header = (
        f"📩 <b>Yangi murojaat</b>\n"
        f"👤 {user.full_name} (@{user.username or '—'})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"↩️ Javob berish uchun shu xabarga (pastdagi forward qilingan xabarga) "
        f"<b>reply</b> qiling — javobingiz avtomatik foydalanuvchiga yetadi."
    )

    sent_to_any = False
    for admin_id in ADMIN_USER_IDS:
        try:
            await context.bot.send_message(admin_id, header, parse_mode="HTML")
            forwarded = await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=msg.message_id,
            )
            _relay_map[(admin_id, forwarded.message_id)] = update.effective_chat.id
            sent_to_any = True
        except Exception:  # noqa: BLE001
            logger.exception("Adminga (%s) murojaatni forward qilishda xatolik", admin_id)

    if sent_to_any:
        await msg.reply_text("✅ Xabaringiz adminga yuborildi. Tez orada javob berishadi.")
    else:
        await msg.reply_text("❌ Adminga yuborib bo'lmadi. Keyinroq qayta urinib ko'ring.")


async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin forward qilingan murojaatga 'reply' qilganda ishga tushadi —
    javobni asl foydalanuvchiga qaytaradi."""
    msg = update.message
    admin_id = update.effective_user.id

    if not msg.reply_to_message:
        return

    target_chat_id = _relay_map.get((admin_id, msg.reply_to_message.message_id))
    if target_chat_id is None:
        return  # bu reply bizning relay tizimimizga aloqador emas

    try:
        await context.bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=admin_id,
            message_id=msg.message_id,
        )
        await msg.reply_text("✅ Javobingiz foydalanuvchiga yuborildi.")
    except Exception as e:  # noqa: BLE001
        logger.exception("Javobni foydalanuvchiga yuborishda xatolik")
        await msg.reply_text(f"❌ Yuborib bo'lmadi: {e}")

    # Bu reply bizning relay tizimimizga tegishli edi — boshqa handlerlar
    # (masalan admin panel conversation) shu xabarni qayta ishlamasin.
    raise ApplicationHandlerStop


# --------------------------------------------------------------------------
# /start va asosiy menyu
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user

    if not ac.is_whitelisted(user.id):
        keyboard = [[InlineKeyboardButton("📩 Adminga murojaat qilish", callback_data="contact_admin")]]
        await update.message.reply_text(
            "🚫 Kechirasiz, botdan foydalanish uchun ruxsatingiz yo'q.\n\n"
            f"Sizning ID'ingiz: <code>{user.id}</code>\n\n"
            "Quyidagi tugma orqali adminga to'g'ridan-to'g'ri xabar (yoki fayl) "
            "yuborishingiz mumkin:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📊 Prezentatsiya yaratish", callback_data="mode_preso")],
        [InlineKeyboardButton("📈 Diagramma yaratish", callback_data="mode_diagram")],
        [InlineKeyboardButton("🗂 Fayl bilan ishlash (AI)", callback_data="mode_file")],
    ]
    text = (
        "Salom! 👋 Men Groq AI yordamida PowerPoint (.pptx) prezentatsiya va "
        "diagrammalar yarataman, shuningdek Word/Excel/PDF fayllar bilan ham "
        "ishlashingizga yordam beraman.\n\n"
        "Nima qilishni xohlaysiz?"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_MODE


async def mode_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await _safe_answer(query)

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

    elif query.data == "mode_file":
        context.user_data["file_history"] = []
        await query.edit_message_text(
            "🗂 <b>Fayl bilan ishlash rejimi</b>\n\n"
            "Menga Word/Excel/PowerPoint/PDF fayl yuboring (izoh — caption — bilan "
            "nima qilish kerakligini yozib), yoki shunchaki matn bilan so'rang "
            "(masalan: <i>\"hisobot.docx yarat, sarlavhasi 'Hisobot' bo'lsin\"</i>).\n\n"
            "Chiqish uchun /done yozing.",
            parse_mode="HTML",
        )
        return FILE_ASSISTANT

    return CHOOSING_MODE


async def file_assistant_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("file_history", None)
    context.user_data.pop("file_pending_upload", None)
    await update.message.reply_text("Fayl rejimidan chiqdingiz. /start bilan qayta boshlashingiz mumkin.")
    return ConversationHandler.END


async def file_assistant_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fayl-yordamchi rejimida kelgan xabarni (fayl va/yoki matn) qayta ishlaydi."""
    user = update.effective_user
    message = update.message

    if not await _check_limit(update, context):
        return FILE_ASSISTANT

    uploaded_note = ""

    # Agar xabarda fayl (document) bo'lsa — yuklab olib, foydalanuvchi papkasiga saqlaymiz.
    if message.document:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        tg_file = await message.document.get_file()
        tmp_path = os.path.join("generated_files", f"_tmp_{user.id}_{message.document.file_unique_id}_{message.document.file_name}")
        os.makedirs("generated_files", exist_ok=True)
        await tg_file.download_to_drive(tmp_path)
        saved_path = file_assistant.save_uploaded_file(user.id, tmp_path, message.document.file_name)
        uploaded_note = f"[Foydalanuvchi '{message.document.file_name}' nomli faylni yubordi]\n"

    user_text = (message.caption or message.text or "").strip()
    if not user_text and message.document:
        user_text = "Bu faylni tahlil qiling va tarkibi haqida qisqacha ayting."
    elif not user_text:
        await message.reply_text("Iltimos, nima qilish kerakligini matn bilan yozing (yoki fayl yuboring).")
        return FILE_ASSISTANT

    history = context.user_data.get("file_history", [])

    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    try:
        # run_file_assistant() ichida Groq'ga sinxron so'rov ketadi — bloklamaslik uchun
        # alohida oqimga chiqaramiz.
        reply_text, touched_files = await asyncio.to_thread(
            file_assistant.run_file_assistant,
            user_id=user.id, history=history, user_message=uploaded_note + user_text,
        )
    except file_assistant.FileAssistantError as e:
        await message.reply_text(f"❌ Xatolik: {e}")
        return FILE_ASSISTANT

    history.append({"role": "user", "content": uploaded_note + user_text})
    history.append({"role": "assistant", "content": reply_text})
    context.user_data["file_history"] = history[-file_assistant.MAX_HISTORY_MESSAGES:]

    await message.reply_text(reply_text)

    for path in touched_files:
        if os.path.exists(path):
            await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            with open(path, "rb") as f:
                await message.reply_document(document=f, filename=os.path.basename(path))

    return FILE_ASSISTANT


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
    await _safe_answer(query)
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
        # Groq (sinxron) + pptx qurish — asyncio.to_thread orqali bloklamasdan.
        data = await asyncio.to_thread(groq_client.generate_presentation, topic, num_slides)
        filepath = await asyncio.to_thread(pptx_builder.build_presentation_file, data)

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
    await _safe_answer(query)
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
        # Groq (sinxron) + pptx qurish — asyncio.to_thread orqali bloklamasdan.
        data = await asyncio.to_thread(groq_client.generate_diagram_data, description, hint)
        filepath = await asyncio.to_thread(pptx_builder.build_diagram_file, data)

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


# --------------------------------------------------------------------------
# ADMIN PANEL — faqat config.ADMIN_USER_IDS'dagi foydalanuvchilar uchun.
# To'liq inline tugmalar orqali boshqariladi (matn buyruq yozish shart emas).
# --------------------------------------------------------------------------

def _parse_limit(text: str):
    """'5' -> 5, 'infinity'/'inf'/'cheksiz' -> None. Noto'g'ri bo'lsa ValueError."""
    text = text.strip().lower()
    if text in ("infinity", "inf", "cheksiz", "unlimited", "-1"):
        return None
    return int(text)


def _admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Foydalanuvchi qo'shish", callback_data="admin_add")],
        [InlineKeyboardButton("✏️ Limitni o'zgartirish", callback_data="admin_setlimit")],
        [InlineKeyboardButton("➖ Foydalanuvchini o'chirish", callback_data="admin_remove")],
        [InlineKeyboardButton("📋 Ro'yxatni ko'rish", callback_data="admin_list")],
    ])


def _format_user_list() -> str:
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
    return "\n".join(lines)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not ac.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🛠 <b>Admin panel</b>\n\nKerakli amalni tanlang:",
        parse_mode="HTML",
        reply_markup=_admin_menu_keyboard(),
    )
    return ADMIN_MENU


async def admin_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await _safe_answer(query)
    action = query.data

    if action == "admin_add":
        await query.edit_message_text(
            "➕ Yangi foydalanuvchi qo'shish.\n\n"
            "<code>user_id limit</code> ko'rinishida yuboring.\n"
            "Masalan: <code>123456789 5</code> (kuniga 5 marta)\n"
            "yoki: <code>123456789 infinity</code> (cheksiz)",
            parse_mode="HTML",
        )
        return ADMIN_WAIT_ADD

    elif action == "admin_setlimit":
        await query.edit_message_text(
            "✏️ Limitni o'zgartirish.\n\n"
            "<code>user_id limit</code> ko'rinishida yuboring.\n"
            "Masalan: <code>123456789 10</code> yoki <code>123456789 infinity</code>",
            parse_mode="HTML",
        )
        return ADMIN_WAIT_SETLIMIT

    elif action == "admin_remove":
        await query.edit_message_text(
            "➖ O'chiriladigan foydalanuvchining <code>user_id</code>'sini yuboring.",
            parse_mode="HTML",
        )
        return ADMIN_WAIT_REMOVE

    elif action == "admin_list":
        await query.edit_message_text(
            _format_user_list(),
            parse_mode="HTML",
            reply_markup=_admin_menu_keyboard(),
        )
        return ADMIN_MENU

    return ADMIN_MENU


async def admin_add_or_setlimit_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.strip().split()
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Format noto'g'ri. Yuboring: <code>user_id limit</code>\n"
            "Masalan: <code>123456789 5</code>",
            parse_mode="HTML",
        )
        return ADMIN_WAIT_ADD

    try:
        target_id = int(parts[0])
        limit = _parse_limit(parts[1])
    except ValueError:
        await update.message.reply_text("❌ user_id butun son, limit esa son yoki 'infinity' bo'lishi kerak.")
        return ADMIN_WAIT_ADD

    ac.add_user(target_id, limit)
    limit_text = "cheksiz" if limit is None else str(limit)
    await update.message.reply_text(
        f"✅ Foydalanuvchi <code>{target_id}</code> qo'shildi/yangilandi. Kunlik limit: {limit_text}.",
        parse_mode="HTML",
        reply_markup=_admin_menu_keyboard(),
    )
    return ADMIN_MENU


async def admin_remove_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ user_id butun son bo'lishi kerak. Qayta yuboring.")
        return ADMIN_WAIT_REMOVE

    removed = ac.remove_user(target_id)
    text = (f"✅ Foydalanuvchi <code>{target_id}</code> whitelist'dan o'chirildi." if removed
            else f"⚠️ Foydalanuvchi <code>{target_id}</code> whitelist'da topilmadi.")
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=_admin_menu_keyboard())
    return ADMIN_MENU


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Admin panel yopildi.")
    return ConversationHandler.END


async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Eski matn-buyruq (/listusers) — hamon ishlayveradi, /admin panel bilan bir xil natija."""
    if not ac.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Bu buyruq faqat administratorlar uchun.")
        return
    await update.message.reply_text(_format_user_list(), parse_mode="HTML")


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
            FILE_ASSISTANT: [
                MessageHandler((filters.Document.ALL | filters.TEXT) & ~filters.COMMAND, file_assistant_message),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("done", file_assistant_done)],
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel)],
        states={
            ADMIN_MENU: [CallbackQueryHandler(admin_menu_router, pattern="^admin_")],
            ADMIN_WAIT_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_or_setlimit_received)],
            ADMIN_WAIT_SETLIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_or_setlimit_received)],
            ADMIN_WAIT_REMOVE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_received)],
        },
        fallbacks=[CommandHandler("cancel", admin_cancel)],
    )

    # Eng yuqori ustuvorlik (group=-1): admin forward qilingan murojaatga
    # "reply" qilsa, boshqa hech qanday handler aralashmasdan to'g'ridan-to'g'ri
    # foydalanuvchiga yetkaziladi.
    if ADMIN_USER_IDS:
        app.add_handler(
            MessageHandler(filters.REPLY & filters.User(user_id=list(ADMIN_USER_IDS)), admin_reply_handler),
            group=-1,
        )

    app.add_handler(conv_handler)
    app.add_handler(admin_conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("listusers", list_users_command))
    app.add_handler(CallbackQueryHandler(preview_slides_callback, pattern="^preview_slides$"))
    app.add_handler(CallbackQueryHandler(contact_admin_button, pattern="^contact_admin$"))
    # Eng oxirida — yuqoridagi hech biriga to'g'ri kelmagan xabarlar uchun
    # ("adminga murojaat" rejimidagi matn/rasm/fayllarni ushlab qoladi).
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, relay_to_admin_or_fallback))

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
