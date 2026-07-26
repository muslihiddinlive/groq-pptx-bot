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
# Boshqa modellar: "llama-3.1-8b-instant" (tezroq), "openai/gpt-oss-120b" va h.k.
# To'liq ro'yxat: https://console.groq.com/docs/models
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

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
