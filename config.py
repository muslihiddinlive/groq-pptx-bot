"""
Konfiguratsiya — barcha maxfiy kalitlar va sozlamalar shu yerdan o'qiladi.
.env faylini to'ldirishni unutmang (.env.example ga qarang).
"""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# --------------------------------------------------------------------------
# Groq API kalitlari — bittadan ko'p bo'lishi mumkin (navbat/round-robin uchun).
# .env faylida GROQ_API_KEYS=gsk_key1,gsk_key2,gsk_key3 ko'rinishida vergul bilan
# ajratib yozing. Eski GROQ_API_KEY (bitta kalit) ham hamon ishlaydi.
# --------------------------------------------------------------------------
_raw_keys = os.getenv("GROQ_API_KEYS", "").strip()
if not _raw_keys:
    _raw_keys = os.getenv("GROQ_API_KEY", "").strip()

GROQ_API_KEYS = [k.strip() for k in _raw_keys.split(",") if k.strip()]

# Groq'da mavjud tez va sifatli modellardan biri.
# DIQQAT: Groq vaqti-vaqti bilan ba'zi modellarni eskirtirib, o'chirib tashlaydi
# (masalan llama-3.3-70b-versatile va llama-3.1-8b-instant 2026-yil avgustidan
# beri o'chirilgan). Joriy ro'yxat: https://console.groq.com/docs/models
# Bu yerdagi qiymat FAQAT bot birinchi marta ishga tushganda ishlatiladigan
# standart holat — keyinchalik /admin panel orqali (Render'ga kirmasdan)
# o'zgartirish mumkin, natija SQLite bazasida saqlanadi.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# --------------------------------------------------------------------------
# Zaxira (fallback) modellar — agar joriy model vaqtincha mavjud bo'lmasa/
# xatolik bersa (masalan "model_not_found"), bot avtomatik ravishda shu
# ro'yxatdagi keyingi modelga o'tadi. Barchasi tool-calling (function
# calling) va JSON-mode'ni qo'llab-quvvatlaydi.
# .env da GROQ_FALLBACK_MODELS=model1,model2 bilan o'zgartirish mumkin.
# --------------------------------------------------------------------------
_raw_fallbacks = os.getenv("GROQ_FALLBACK_MODELS", "").strip()
if _raw_fallbacks:
    GROQ_FALLBACK_MODELS = [m.strip() for m in _raw_fallbacks.split(",") if m.strip()]
else:
    GROQ_FALLBACK_MODELS = ["openai/gpt-oss-20b", "moonshotai/kimi-k2-instruct"]

# Asosiy model + zaxiralar — takrorlanishlarsiz, tartib saqlangan holda.
# ESLATMA: bu STATIK zanjir (.env asosida) — admin panel orqali o'zgartirilgan
# joriy model buni HISOBGA OLMAYDI. Dinamik (admin-panel bilan birga
# ishlaydigan) zanjir uchun groq_client.py/file_assistant.py ichidagi
# _model_chain() funksiyasiga qarang.
GROQ_MODEL_CHAIN = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]

# Har bir generatsiyada nechta so'rov (retry/kalitlar bo'yicha) qilishga ruxsat berilsin.
# Agar bir nechta kalit bo'lsa, avtomatik ravishda kamida shuncha marta (yoki kalitlar
# sonicha, qaysi biri katta bo'lsa) urinib ko'riladi.
GROQ_MAX_RETRIES = 3

# --------------------------------------------------------------------------
# DB kanal — har bir yaratilgan fayl va so'rov tarixi shu (xususiy) Telegram
# kanaliga log sifatida yuboriladi. Botni kanalga ADMIN qilib qo'shing va
# kanal ID'sini (masalan -1001234567890) shu yerga yozing. Bo'sh qoldirsa,
# bu funksiya o'chiq bo'ladi.
# --------------------------------------------------------------------------
_raw_db_channel = os.getenv("DB_CHANNEL_ID", "").strip()
DB_CHANNEL_ID = int(_raw_db_channel) if _raw_db_channel.lstrip("-").isdigit() else None

# Vaqtinchalik fayllar saqlanadigan papka (tayyor pptx shu yerga yoziladi)
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "generated_files")
os.makedirs(OUTPUT_DIR, exist_ok=True)

if not TELEGRAM_BOT_TOKEN:
    print("OGOHLANTIRISH: TELEGRAM_BOT_TOKEN .env faylida topilmadi!")
if not GROQ_API_KEYS:
    print("OGOHLANTIRISH: GROQ_API_KEY(S) .env faylida topilmadi!")
if not DB_CHANNEL_ID:
    print("MA'LUMOT: DB_CHANNEL_ID sozlanmagan — tarix hech qayerga saqlanmaydi.")

# --------------------------------------------------------------------------
# Ruxsat nazorati (whitelist + admin panel)
# --------------------------------------------------------------------------
# ADMIN_USER_IDS — bularning Telegram user_id'lari doim botdan CHEKSIZ
# foydalana oladi va /admin panelga kira oladi. .env fayliga vergul bilan
# ajratib yozing: ADMIN_USER_IDS=123456789,987654321
# O'zingizning Telegram ID'ingizni bilish uchun @userinfobot ga yozing.
_raw_admins = os.getenv("ADMIN_USER_IDS", "").strip()
ADMIN_USER_IDS = {int(x.strip()) for x in _raw_admins.split(",") if x.strip().lstrip("-").isdigit()}

# Whitelist va foydalanish statistikasi saqlanadigan SQLite fayli.
# DIQQAT: Render'ning bepul rejasida persistent disk yo'q — bu fayl har
# qayta deploy/restart'da NOLGA tushadi. Doimiy saqlash kerak bo'lsa,
# Render'da "Persistent Disk" (pullik) qo'shing yoki tashqi DB ishlating.
DB_PATH = os.getenv("DB_PATH", "bot_access.db")

if not ADMIN_USER_IDS:
    print("MA'LUMOT: ADMIN_USER_IDS sozlanmagan — /admin panelga hech kim kira olmaydi "
          "va whitelist bo'sh bo'lsa, HECH KIM botdan foydalana olmaydi!")
