# Groq PPTX Telegram Bot

Groq API (LLM) yordamida mavzu bo'yicha **PowerPoint prezentatsiya** yoki
alohida **diagramma** (pie, bar, line, flowchart, org chart, Venn, timeline)
yaratadigan Telegram bot.

- 🖼 **Slaydlarni rasm sifatida ko'rish** — har bir yaratilgan `.pptx` fayl
  ostida inline tugma chiqadi. Bosilganda, bot har bir slaydni alohida PNG
  rasmga aylantirib, albom (media group) sifatida yuboradi — PowerPoint
  ochmasdan turib slaydlarni tezda ko'rish mumkin.

  **Talab:** bu funksiya ishlashi uchun kompyuteringizda **LibreOffice**
  o'rnatilgan bo'lishi kerak (bepul):
  https://www.libreoffice.org/download/download/
  O'rnatgandan so'ng botni qayta ishga tushiring — standart o'rnatish yo'li
  avtomatik topiladi. Agar boshqa joyga o'rnatgan bo'lsangiz, `.env` fayliga
  qo'shing: `SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe`

## Render.com'da bepul deploy qilish (LibreOffice o'rnatish shart emas!)

Bot avtomatik ravishda ikki rejimda ishlashi mumkin:
- **Lokal kompyuterda** (Windows va h.k.) → oddiy **polling** rejimi (hech narsa sozlash shart emas, hozirgi ishlash tartibi).
- **Render'da** → avtomatik **webhook** rejimiga o'tadi (`RENDER_EXTERNAL_URL` mavjudligini aniqlab).

Bitta kod — ikkala joyda ham ishlaydi.

### Nega Render?

- **Bepul** ("Free" Web Service reja, $0/oy).
- `Dockerfile` orqali LibreOffice **serverning o'ziga** avtomatik o'rnatiladi — sizga hech narsa o'rnatish shart emas.
- ⚠️ Cheklov: bepul reja 15 daqiqa harakatsizlikdan keyin "uxlab qoladi". Birinchi xabar kelganda uni "uyg'otish" 30-60 soniya vaqt olishi mumkin — bu normal holat, keyingi xabarlar tezroq ishlaydi. (Doim uyg'oq turishini xohlasangiz, [cron-job.org](https://cron-job.org) kabi bepul xizmat orqali har 10 daqiqada saytingizga so'rov yuborib turishingiz mumkin.)

### Qadamlar

1. **[render.com](https://render.com)**da ro'yxatdan o'ting (GitHub akkountingiz bilan kirsangiz qulay).
2. Dashboard'da **"New +"** → **"Blueprint"** ni bosing.
3. `muslihiddinlive/groq-pptx-bot` repongizni tanlang (yoki ulang). Render repodagi `render.yaml` faylini avtomatik o'qib, barcha sozlamalarni tayyorlaydi.
4. So'raladigan maxfiy o'zgaruvchilarni (environment variables) kiriting:
   - `TELEGRAM_BOT_TOKEN` — @BotFather'dan olgan token
   - `GROQ_API_KEYS` — Groq kalit(lar)ingiz (vergul bilan ajratib, bir nechtasi bo'lsa)
   - `DB_CHANNEL_ID` — (ixtiyoriy) tarix saqlanadigan kanal ID
5. **"Apply"** / **"Deploy"** tugmasini bosing. Birinchi deploy ~3-5 daqiqa vaqt oladi (LibreOffice o'rnatilishi sabab).
6. Deploy tugagach, loglarda `WEBHOOK rejimida ishga tushmoqda: https://...` degan qatorni ko'rasiz — bu bot muvaffaqiyatli ishga tushganini bildiradi.
7. Telegram'da botingizga `/start` yuboring — javob berishi kerak (agar uxlab qolgan bo'lsa, birinchi javob biroz kechikishi mumkin).

### Qo'lda deploy qilish (Blueprint ishlamasa)

1. **"New +"** → **"Web Service"**.
2. GitHub repongizni ulang, **Runtime: Docker** tanlang.
3. **Instance Type: Free**.
4. Environment bo'limida yuqoridagi 3 ta o'zgaruvchini qo'lda qo'shing.
5. **Create Web Service**.

### Yangilanishlarni deploy qilish

`main` branch'ga har safar `git push` qilganingizda, Render avtomatik ravishda qayta deploy qiladi (auto-deploy yoqilgan bo'lsa — bu standart sozlama).

- 🔐 **Whitelist + Admin panel** — botdan faqat ruxsat etilgan foydalanuvchilar
  foydalana oladi. Har biriga kunlik generatsiya limiti belgilanadi (admin
  cheksiz). Butunlay bot ichidagi buyruqlar orqali boshqariladi, alohida
  sayt/panel kerak emas.

  **Sozlash:**
  1. Telegram'da o'z ID'ingizni bilib oling: [@userinfobot](https://t.me/userinfobot)ga yozing.
  2. `.env` fayliga qo'shing: `ADMIN_USER_IDS=123456789` (bir nechta admin bo'lsa vergul bilan).
  3. Botni ishga tushiring — endi sizga (admin) hech qanday cheklov yo'q.

  **Admin panel** — endi to'liq **inline tugmalar** orqali boshqariladi:
  - `/admin` buyrug'ini yuboring — tugmali menyu chiqadi:
    - ➕ **Foydalanuvchi qo'shish** — bosgach, `user_id limit` yozib yuborasiz
      (masalan: `123456789 5` yoki `123456789 infinity`)
    - ✏️ **Limitni o'zgartirish** — xuddi shunday
    - ➖ **Foydalanuvchini o'chirish** — faqat `user_id` yuborasiz
    - 📋 **Ro'yxatni ko'rish** — barcha whitelist va bugungi foydalanishlar
  - `/listusers` — tezkor matn-buyruq (ro'yxatni to'g'ridan-to'g'ri ko'rsatadi)

  Ruxsati yo'q foydalanuvchi `/start` bosganda, bot unga o'z ID'sini va
  **"📩 Adminga murojaat qilish"** tugmasini ko'rsatadi.

- 📩 **Adminga to'g'ridan-to'g'ri murojaat (ikki tomonlama)** — ruxsati yo'q
  foydalanuvchi "Adminga murojaat qilish" tugmasini bossa, botga yozgan
  keyingi xabari (matn, rasm, hujjat — istalgani) avtomatik barcha
  adminlarga yuboriladi, jo'natuvchining ismi/ID'si bilan birga. Admin esa
  o'sha xabarga oddiy Telegram **"Reply"** (javob berish) orqali javob
  yozsa, javob avtomatik ravishda so'ragan foydalanuvchiga yetkaziladi —
  alohida usernam bilan yozishning hojati yo'q.

  ⚠️ **Eslatma:** whitelist SQLite faylida saqlanadi. Render bepul rejasida bu
  fayl har qayta deploy/restart'da tozalanadi (persistent disk yo'q). Doimiy
  saqlash kerak bo'lsa, Render'da pullik "Persistent Disk" qo'shing.

- 🎨 **Sifatli, xilma-xil prezentatsiya dizayni** — endi Groq shunchaki
  matn+grafikdan iborat emas, balki 10 xil slayd turini aralashtirib,
  professional taqdimotlarga xos tarkib tuzadi: bo'lim ajratuvchilar,
  katta raqam/statistika kartalar, iqtibos slaydlari, ikki tomonlama
  taqqoslash jadvallari va h.k. Har bir slaydda sahifa raqami ham bor.

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
- 🗂 **Fayl bilan ishlash (AI)** — Word/Excel/PowerPoint/PDF fayl yuboring
  (yoki yubormasdan matn bilan so'rang), AI kerakli amalni ([ms-file-toolkit](https://pypi.org/project/ms-file-toolkit/)
  orqali 36 xil funksiya — o'qish, yaratish, tahrirlash, diagramma qo'shish va h.k.)
  bajaradi va natija faylini qaytaradi. Har bir foydalanuvchi fayllari alohida,
  bir-biriga aralashmaydigan papkada saqlanadi (xavfsizlik uchun ikki qatlamli
  himoya bilan).
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
├── slide_renderer.py    # .pptx slaydlarini PNG rasmga aylantirish (LibreOffice + PyMuPDF)
├── file_assistant.py     # "Fayl bilan ishlash (AI)" rejimi — ms-file-toolkit + Groq tool-calling
├── access_control.py    # Whitelist + kunlik limit (SQLite)
├── config.py            # .env dan sozlamalarni o'qish
├── requirements.txt
├── Dockerfile           # Render uchun — LibreOffice shu yerda o'rnatiladi
├── .dockerignore
├── render.yaml           # Render Blueprint (bir-klik deploy sozlamasi)
├── .env.example
└── generated_files/     # Yaratilgan .pptx fayllar shu yerga saqlanadi (avtomatik)
    └── file_assistant/<user_id>/   # Har bir foydalanuvchining o'z fayllari
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

### Avtomatik zaxira (fallback) model

Agar asosiy model (`GROQ_MODEL`) Groq tomonidan vaqtincha mavjud
bo'lmay qolsa (masalan `model_not_found` xatosi — hisobingiz uchun
vaqtincha cheklov yoki Groq tomonidagi uzilish bo'lishi mumkin), bot
buni avtomatik aniqlab, DARHOL keyingi modelga o'tadi (boshqa
kalitlarni behuda sinamaydi, chunki bu model darajasidagi muammo).

Standart zaxira zanjiri: `llama-3.3-70b-versatile` → `llama-3.1-8b-instant`
→ `openai/gpt-oss-120b`. O'zgartirish uchun `.env` ga qo'shing:

```
GROQ_FALLBACK_MODELS=llama-3.1-8b-instant,openai/gpt-oss-120b
```

Bu fallback ham prezentatsiya/diagramma generatsiyasida, ham
"Fayl bilan ishlash (AI)" rejimida ishlaydi.

## Kengaytirish g'oyalari

- Rate-limiting / foydalanuvchi bo'yicha kunlik limit qo'shish.
- Prezentatsiya uchun shablon (template) tanlash imkonini qo'shish.
- Natijani PDF formatida ham yuborish (`soffice --headless --convert-to pdf`).
- Yaratilgan fayllarni ma'lum vaqtdan keyin `generated_files/` dan tozalash
  (disk to'lib qolmasligi uchun cron/APScheduler bilan).
