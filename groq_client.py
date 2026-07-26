"""
Groq API bilan ishlash uchun wrapper.
Groq juda tez inferens beradi (LPU asosida), OpenAI'ga o'xshash Chat Completions
API'siga ega, shu jumladan JSON-mode (response_format={"type": "json_object"}) ni
qo'llab-quvvatlaydi — biz buni strukturaланgan (slaydlar/diagramma) ma'lumot olish
uchun ishlatamiz.

Rasmiy SDK: `pip install groq`  |  Docs: https://console.groq.com/docs
"""
import json
import logging
import threading

from groq import Groq

from config import GROQ_API_KEYS, GROQ_MODEL, GROQ_MAX_RETRIES

logger = logging.getLogger(__name__)


class GroqGenerationError(Exception):
    """Groq javobini olishda yoki JSON parse qilishda xatolik yuz berganda."""


class KeyPool:
    """
    Bir nechta Groq API kalitini navbat (round-robin) tartibida beradi.

    Har bir yangi so'rov oldingi so'rovdan KEYINGI kalitdan boshlanadi — shu
    tariqa yuklama barcha kalitlar orasida teng taqsimlanadi. Agar bitta kalit
    ishlamay qolsa (masalan rate-limit), keyingi kalit avtomatik sinab ko'riladi.
    """

    def __init__(self, keys: list[str]):
        self._keys = keys
        self._lock = threading.Lock()
        self._next_idx = 0

    def __len__(self):
        return len(self._keys)

    def has_keys(self) -> bool:
        return len(self._keys) > 0

    def attempt_sequence(self, n: int) -> list[str]:
        """So'rov uchun sinab ko'riladigan kalitlar ketma-ketligini qaytaradi
        (uzunligi n, boshlanish nuqtasi har chaqiriqda bir pog'ona siljiydi)."""
        if not self._keys:
            return []
        with self._lock:
            start = self._next_idx
            self._next_idx = (self._next_idx + 1) % len(self._keys)
        return [self._keys[(start + i) % len(self._keys)] for i in range(n)]


_key_pool = KeyPool(GROQ_API_KEYS)


def _mask(key: str) -> str:
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***"


def _chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.6) -> dict:
    """
    Groq'ga so'rov yuboradi va JSON obyekt qaytarishini kutadi.
    Bir nechta API kalit bo'lsa, ular orasida navbat bilan (round-robin) va
    xatolik/limit holatida keyingi kalitga o'tib sinab ko'riladi.
    """
    if not _key_pool.has_keys():
        raise GroqGenerationError(
            "Hech qanday Groq API kaliti sozlanmagan. .env fayliga "
            "GROQ_API_KEYS=kalit1,kalit2,... qo'shing."
        )

    n_attempts = max(len(_key_pool), GROQ_MAX_RETRIES)
    keys_to_try = _key_pool.attempt_sequence(n_attempts)

    last_error = None
    for attempt, key in enumerate(keys_to_try, start=1):
        client = Groq(api_key=key)
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
                max_tokens=4000,
            )
            raw = completion.choices[0].message.content
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning("Urinish %s/%s (kalit %s): Groq JSON qaytarmadi (%s)",
                            attempt, len(keys_to_try), _mask(key), e)
        except Exception as e:  # noqa: BLE001 - Groq/tarmoq xatolarini ham ushlaymiz
            last_error = e
            msg = str(e).lower()
            reason = "limit/kvota tugagan" if any(w in msg for w in ("rate", "429", "quota")) else "xatolik"
            logger.warning("Urinish %s/%s (kalit %s): %s (%s)",
                            attempt, len(keys_to_try), _mask(key), reason, e)

    raise GroqGenerationError(
        f"Groq'dan {len(keys_to_try)} urinishdan (kalitlar bo'yicha) keyin ham "
        f"to'g'ri javob olinmadi: {last_error}"
    )


# --------------------------------------------------------------------------
# 1) TO'LIQ PREZENTATSIYA KONTENTINI GENERATSIYA QILISH
# --------------------------------------------------------------------------

PRESENTATION_SYSTEM_PROMPT = """Sen professional prezentatsiya kontent-strategisan.
Foydalanuvchi bergan mavzu asosida PowerPoint prezentatsiyasi uchun tarkib tuzasan.
Javobni FAQAT quyidagi JSON formatida qaytar, boshqa hech qanday matn, izoh yoki
markdown qo'shma:

{
  "title": "Prezentatsiya sarlavhasi",
  "subtitle": "Qisqa pastki sarlavha",
  "slides": [
    {
      "type": "content",
      "title": "Slayd sarlavhasi",
      "bullets": ["Qisqa va aniq fikr 1", "Qisqa va aniq fikr 2", "..."]
    },
    {
      "type": "chart",
      "title": "Slayd sarlavhasi",
      "chart_type": "pie" | "bar" | "line" | "donut",
      "series_name": "Ma'lumot nomi",
      "categories": ["Toifa1", "Toifa2", "..."],
      "values": [12, 34, "..."]
    },
    {
      "type": "flowchart",
      "title": "Slayd sarlavhasi",
      "steps": ["1-bosqich", "2-bosqich", "3-bosqich"]
    },
    {
      "type": "orgchart",
      "title": "Slayd sarlavhasi",
      "root": "Bosh element",
      "children": ["Element1", "Element2", "Element3"]
    }
  ]
}

Qoidalar:
- Bullets qisqa bo'lsin (har biri 12 so'zdan oshmasin), gap emas, fikr sifatida.
- Har bir slaydda 3-5 ta bullet bo'lsin (content turi uchun).
- Mavzuga mos bo'lsa, kamida 1 ta "chart" yoki "flowchart"/"orgchart" turidagi slayd qo'sh —
  prezentatsiya faqat matndan iborat bo'lmasin.
- Chart uchun raqamlar realistik va mantiqiy bo'lsin.
- Foydalanuvchi so'ragan tildan boshqa tilda javob berma."""


def generate_presentation(topic: str, num_slides: int, language: str = "o'zbek") -> dict:
    """
    Mavzu bo'yicha to'liq prezentatsiya strukturasini (JSON) generatsiya qiladi.

    :param topic: Prezentatsiya mavzusi (foydalanuvchi kiritgan matn)
    :param num_slides: Nechta kontent slayd kerakligi (title slide bundan tashqari)
    :param language: Javob qaysi tilda bo'lishi kerak
    :return: dict — yuqoridagi JSON sxemasiga mos
    """
    user_prompt = (
        f"Mavzu: {topic}\n"
        f"Slaydlar soni (title slide'dan tashqari): {num_slides}\n"
        f"Til: {language}\n"
        f"Shu mavzuda professional, qiziqarli va foydali prezentatsiya tarkibini tuz."
    )
    data = _chat_json(PRESENTATION_SYSTEM_PROMPT, user_prompt, temperature=0.7)

    if "slides" not in data or "title" not in data:
        raise GroqGenerationError(f"Groq javobi kutilgan sxemaga mos emas: {data}")

    return data


# --------------------------------------------------------------------------
# 2) FAQAT BITTA DIAGRAMMA UCHUN MA'LUMOT GENERATSIYA QILISH
# --------------------------------------------------------------------------

DIAGRAM_SYSTEM_PROMPT = """Sen ma'lumotlarni vizualizatsiya uchun tayyorlaydigan yordamchisan.
Foydalanuvchi biror diagramma turini va uning mazmunini tavsiflaydi (masalan,
"IT bo'limi tarkibi", "2024-yil sotuvlar taqsimoti", "mahsulot ishlab chiqarish jarayoni").
Sen shu tavsifga mos ravishda diagramma uchun aniq ma'lumotlarni generatsiya qilasan.

Diagramma turiga qarab, JAVOBNI FAQAT quyidagi JSON formatlaridan BIRIDA qaytar:

Agar chart_type "pie", "bar", "line" yoki "donut" bo'lsa:
{
  "diagram_type": "chart",
  "chart_type": "pie",
  "title": "Diagramma sarlavhasi",
  "series_name": "Ma'lumot nomi",
  "categories": ["Toifa1", "Toifa2", "..."],
  "values": [12, 34, "..."]
}

Agar jarayon/bosqichlar haqida bo'lsa (flowchart):
{
  "diagram_type": "flowchart",
  "title": "Diagramma sarlavhasi",
  "steps": ["1-bosqich", "2-bosqich", "3-bosqich", "4-bosqich"]
}

Agar tashkiliy tuzilma / ierarxiya haqida bo'lsa (orgchart):
{
  "diagram_type": "orgchart",
  "title": "Diagramma sarlavhasi",
  "root": "Bosh element",
  "children": ["Element1", "Element2", "Element3", "Element4"]
}

Agar ikkita tushunchaning kesishishi/o'xshashligi haqida bo'lsa (Venn diagram):
{
  "diagram_type": "venn",
  "title": "Diagramma sarlavhasi",
  "set_a": "Birinchi to'plam nomi",
  "set_b": "Ikkinchi to'plam nomi",
  "overlap": "Ikkalasiga ham tegishli narsa"
}

Agar vaqt bo'yicha voqealar ketma-ketligi haqida bo'lsa (timeline):
{
  "diagram_type": "timeline",
  "title": "Diagramma sarlavhasi",
  "events": [{"date": "2021", "label": "Voqea tavsifi"}, {"date": "2022", "label": "..."}]
}

Foydalanuvchi tavsifiga eng mos formatni TANLA. Faqat JSON qaytar, boshqa matn qo'shma."""


def generate_diagram_data(description: str, diagram_hint: str = "") -> dict:
    """
    Foydalanuvchi tavsifi asosida bitta diagramma uchun struktura generatsiya qiladi.

    :param description: Foydalanuvchi yozgan tavsif (masalan: "3 ta bo'lim: sotuv 40%,
                         marketing 35%, IT 25%")
    :param diagram_hint: Foydalanuvchi tanlagan diagramma turi (pie/bar/line/flowchart/
                          orgchart/venn/timeline) — bo'sh bo'lishi ham mumkin, shunda
                          Groq o'zi eng mos turni tanlaydi.
    """
    hint_text = f"\nFoydalanuvchi xohlagan diagramma turi: {diagram_hint}" if diagram_hint else ""
    user_prompt = f"Tavsif: {description}{hint_text}"
    data = _chat_json(DIAGRAM_SYSTEM_PROMPT, user_prompt, temperature=0.5)

    if "diagram_type" not in data:
        raise GroqGenerationError(f"Groq javobida 'diagram_type' topilmadi: {data}")

    return data
