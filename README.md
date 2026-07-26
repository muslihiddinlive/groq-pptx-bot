# Groq PPTX Telegram Bot

Groq API (LLM) yordamida mavzu bo'yicha **PowerPoint prezentatsiya** yoki
alohida **diagramma** (pie, bar, line, flowchart, org chart, Venn, timeline)
yaratadigan Telegram bot.

## Yangi imkoniyatlar

- 🔑 **Bir nechta Groq API kalit** — `.env` da `GROQ_API_KEYS=kalit1,kalit2,...`
  ko'rinishida istagancha kalit qo'shishingiz mumkin. Bot har bir so'rovda
  kalitlar orasida **navbat (round-robin)** bilan aylanadi — bu bepul
  limitlarni bir nechta akkount/kalit orasida taqsimlab, tezroq va uzluksiz
  ishlashga yordam beradi. Agar biror kalit limitga yetib xato qaytarsa, bot
  avtomatik ravishda **keyingi kalitni** sinab ko'radi.
- 🗂 **DB kanal (tarixni saqlash)** — haqiqiy database o'rniga sodda va
  ishonchli yechim: har bir yaratilgan `.pptx` fayl + so'rovchi (foydalanuvchi
  ismi, username, ID) + so'rov matni avtomatik ravishda sizning **xususiy
  Telegram kanalingizga** log sifatida yuboriladi. Shu kanaldan istalgan
  vaqtda qidirish, eksport qilish yoki tahlil qilish mumkin.

  **Sozlash:**
  1. Telegram'da yangi **xususiy kanal** yarating (masalan "Bot DB Log").
  2. Botingizni shu kanalga **admin** qilib qo'shing (kamida "Post messages"
     huquqi bilan).
  3. Kanal ID'sini oling — eng oson yo'li: kanalga istalgan xabar yuboring,
     so'ng [@userinfobot](https://t.me/userinfobot) yoki
     [@getidsbot](https://t.me/getidsbot) orqali forward qiling, ID odatda
     `-100` bilan boshlanadi (masalan `-1001234567890`).
  4. `.env` fayliga `DB_CHANNEL_ID=-1001234567890` deb yozing.

## Imkoniyatlari

- 📊 **Prezentatsiya yaratish** — mavzu va slaydlar sonini kiriting, bot Groq
  orqali kontent generatsiya qiladi va tayyor `.pptx` faylini yuboradi.
  Prezentatsiyaga avtomatik ravishda matnli slaydlar, grafiklar va
  jarayon/tuzilma diagrammalari aralashtirib qo'shiladi.
- 📈 **Faqat diagramma yaratish** — diagramma turini tanlang (yoki AI o'zi
  tanlasin), mazmunini tavsiflab bering — bitta slaydli `.pptx` tayyor bo'ladi.
- Qo'llab-quvvatlanadigan diagramma turlari:
  - 🥧 Pie chart (doiraviy)
  - 📊 Bar chart (ustunli)
  - 📈 Line chart (chiziqli)
  - 🔀 Flowchart (jarayon bosqichlari, o'q-strelkalar bilan)
  - 🏢 Org chart (tashkiliy tuzilma / ierarxiya)
  - ⭕ Venn diagram (ikkita to'plam kesishishi)
  - 🕒 Timeline (vaqt chizig'i)

## O'rnatish

```bash
git clone <repo>
cd groq_pptx_bot
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` faylini oching va quyidagilarni to'ldiring:

1. **TELEGRAM_BOT_TOKEN** — Telegram'da [@BotFather](https://t.me/BotFather)
   ga yozib, `/newbot` orqali yangi bot yarating, tokenni oling.
2. **GROQ_API_KEY** — [console.groq.com/keys](https://console.groq.com/keys)
   saytida ro'yxatdan o'tib, bepul API key oling.

## Ishga tushirish

```bash
python bot.py
```

Telegram'da botingizni toping va `/start` bosing.

## Loyiha tuzilishi

```
groq_pptx_bot/
├── bot.py             # Telegram bot — foydalanuvchi bilan muloqot (ConversationHandler)
├── groq_client.py      # Groq API bilan ishlash, JSON-mode orqali struktura olish
├── pptx_builder.py     # Groq JSON'ini .pptx faylga aylantirish (yuqori daraja)
├── diagrams.py          # python-pptx bilan slayd/grafik/diagramma chizish (past daraja)
├── config.py            # .env dan sozlamalarni o'qish
├── requirements.txt
├── .env.example
└── generated_files/     # Yaratilgan .pptx fayllar shu yerga saqlanadi (avtomatik)
```

## Qanday ishlaydi (arxitektura)

1. Foydalanuvchi `/start` bosadi → rejim tanlaydi (prezentatsiya/diagramma).
2. Bot mavzu/tavsifni so'raydi.
3. `groq_client.py` Groq'ga so'rov yuboradi, **JSON-mode** (`response_format:
   json_object`) yordamida qat'iy strukturalangan javob oladi (slaydlar,
   grafik ma'lumotlari, jarayon bosqichlari va h.k.).
4. `pptx_builder.py` bu JSON'ni `diagrams.py` dagi funksiyalarga uzatadi —
   ular `python-pptx` yordamida haqiqiy slaydlar, native Excel-grafiklar
   (pie/bar/line) va qo'lda chizilgan shakllar (flowchart/orgchart/venn/
   timeline) yaratadi.
5. Tayyor `.pptx` fayl Telegram orqali foydalanuvchiga yuboriladi.

## Modelni almashtirish

`.env` faylida `GROQ_MODEL` ni o'zgartiring. Groq'da mavjud modellar:
https://console.groq.com/docs/models — masalan `llama-3.1-8b-instant`
(tezroq, arzonroq) yoki `openai/gpt-oss-120b`.

## Kengaytirish g'oyalari

- Rate-limiting / foydalanuvchi bo'yicha kunlik limit qo'shish.
- Prezentatsiya uchun shablon (template) tanlash imkonini qo'shish.
- Natijani PDF formatida ham yuborish (`soffice --headless --convert-to pdf`).
- Yaratilgan fayllarni ma'lum vaqtdan keyin `generated_files/` dan tozalash
  (disk to'lib qolmasligi uchun cron/APScheduler bilan).
