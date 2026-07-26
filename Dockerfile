# Groq PPTX Telegram Bot — Render.com uchun Docker image
# LibreOffice shu image ichida bir marta o'rnatiladi, foydalanuvchilarga
# hech qanday aloqasi yo'q — bot ishlab turgan server buni ishlatadi.

FROM python:3.12-slim

# LibreOffice (Impress) — .pptx -> .pdf konvertatsiyasi uchun kerak
# (slide_renderer.py shu binary'ni chaqiradi)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-impress \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render "Web Service" turi $PORT muhit o'zgaruvchisini avtomatik beradi;
# bot.py buni RENDER_EXTERNAL_URL mavjudligiga qarab webhook rejimida ishlatadi.
CMD ["python", "bot.py"]
