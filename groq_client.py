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

from config import GROQ_API_KEYS, GROQ_FALLBACK_MODELS, GROQ_MAX_RETRIES


def _model_chain() -> list[str]:
    """Har chaqiruvda YANGIDAN hisoblanadigan model zanjiri: birinchi o'rinda
    admin panel orqali o'rnatilgan joriy model (yoki .env/standart, agar admin
    hali o'zgartirmagan bo'lsa), keyin config.py'dagi zaxira modellar.
    Har safar yangidan hisoblanishi muhim — shunda admin /admin panelidan
    modelni o'zgartirganda, botni qayta ishga tushirmasdan ham darhol kuchga kiradi."""
    import access_control as ac  # doiraviy import'dan qochish uchun shu yerda
    active = ac.get_active_model()
    return [active] + [m for m in GROQ_FALLBACK_MODELS if m != active]

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


def _is_model_not_found(exc: Exception) -> bool:
    """Groq 'model_not_found' (404 — model mavjud emas yoki ruxsat yo'q) xatosini aniqlaydi."""
    msg = str(exc).lower()
    return "model_not_found" in msg or "does not exist" in msg


def _chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.6, max_tokens: int = 4000) -> dict:
    """
    Groq'ga so'rov yuboradi va JSON obyekt qaytarishini kutadi.

    Ikki bosqichli qayta urinish:
    1) Har bir model (dinamik model zanjiri — admin belgilagan asosiy model + config.py'dagi zaxiralar) uchun,
    2) Har bir Groq API kaliti (round-robin) uchun.

    Agar model "model_not_found" xatosi bersa, DARHOL keyingi modelga o'tiladi
    (chunki bu holatda boshqa kalitni sinash foyda bermaydi — muammo model
    darajasida). Boshqa xatolar (limit/tarmoq) uchun avvalgidek keyingi kalit
    sinaladi.
    """
    if not _key_pool.has_keys():
        raise GroqGenerationError(
            "Hech qanday Groq API kaliti sozlanmagan. .env fayliga "
            "GROQ_API_KEYS=kalit1,kalit2,... qo'shing."
        )

    last_error = None
    model_chain = _model_chain()

    for model in model_chain:
        n_attempts = max(len(_key_pool), GROQ_MAX_RETRIES)
        keys_to_try = _key_pool.attempt_sequence(n_attempts)

        for attempt, key in enumerate(keys_to_try, start=1):
            client = Groq(api_key=key)
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                )
                raw = completion.choices[0].message.content
                return json.loads(raw)
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning("Model %s, urinish %s/%s (kalit %s): Groq JSON qaytarmadi (%s)",
                                model, attempt, len(keys_to_try), _mask(key), e)
            except Exception as e:  # noqa: BLE001 - Groq/tarmoq xatolarini ham ushlaymiz
                last_error = e
                if _is_model_not_found(e):
                    logger.warning("Model %s mavjud emas/ruxsat yo'q — zaxira modelga o'tiladi (%s)", model, e)
                    break  # shu model bilan boshqa kalit sinamaymiz, keyingi modelga o'tamiz
                msg = str(e).lower()
                reason = "limit/kvota tugagan" if any(w in msg for w in ("rate", "429", "quota")) else "xatolik"
                logger.warning("Model %s, urinish %s/%s (kalit %s): %s (%s)",
                                model, attempt, len(keys_to_try), _mask(key), reason, e)

    raise GroqGenerationError(
        f"Groq'dan barcha modellar ({', '.join(model_chain)}) va kalitlar bo'yicha "
        f"urinishdan keyin ham to'g'ri javob olinmadi: {last_error}"
    )


# --------------------------------------------------------------------------
# 1) TO'LIQ PREZENTATSIYA KONTENTINI GENERATSIYA QILISH
# --------------------------------------------------------------------------

PRESENTATION_SYSTEM_PROMPT = """Sen professional prezentatsiya dizayneri va kontent-strategisan
(McKinsey/Apple darajasidagi taqdimotlar tuzasan — quruq matn emas, balki har xil
formatlar bilan boyitilgan, ko'zga yoqimli va ishonarli tarkib).

Foydalanuvchi bergan mavzu asosida PowerPoint prezentatsiyasi uchun tarkib tuzasan.
Javobni FAQAT quyidagi JSON formatida qaytar, boshqa hech qanday matn, izoh yoki
markdown qo'shma:

{
  "title": "Prezentatsiya sarlavhasi",
  "subtitle": "Qisqa pastki sarlavha",
  "slides": [ ... quyidagi turlardan aralashtirib ... ]
}

Slayd turlari (har biri "type" maydoni bilan aniqlanadi):

1. "content" — oddiy matnli slayd:
   {"type": "content", "title": "...", "bullets": ["fikr 1", "fikr 2", "..."]}

2. "chart" — grafik (raqamli ma'lumot uchun):
   {"type": "chart", "title": "...", "chart_type": "pie"|"bar"|"line"|"donut",
    "series_name": "...", "categories": ["...", "..."], "values": [12, 34, "..."]}

3. "flowchart" — jarayon bosqichlari:
   {"type": "flowchart", "title": "...", "steps": ["1-bosqich", "2-bosqich", "..."]}

4. "orgchart" — tashkiliy tuzilma/ierarxiya:
   {"type": "orgchart", "title": "...", "root": "...", "children": ["...", "..."]}

5. "venn" — ikkita tushunchaning kesishishi:
   {"type": "venn", "title": "...", "set_a": "...", "set_b": "...", "overlap": "..."}

6. "timeline" — vaqt bo'yicha voqealar:
   {"type": "timeline", "title": "...", "events": [{"date": "...", "label": "..."}]}

7. "section" — bo'lim ajratuvchi (uzun prezentatsiyalarda mavzuni bo'limlarga
   ajratish uchun, to'liq ekran fon rangli, kontent kam):
   {"type": "section", "title": "Bo'lim nomi", "subtitle": "qisqa izoh (ixtiyoriy)"}

8. "stat" — 2-4 ta katta raqam/ko'rsatkichni ajratib ko'rsatish uchun:
   {"type": "stat", "title": "...", "stats": [{"number": "87%", "label": "tavsif"}, "..."]}

9. "quote" — ta'sirli iqtibos/tsitata slaydi:
   {"type": "quote", "quote": "iqtibos matni", "author": "muallif yoki manba"}

10. "comparison" — ikkita narsani yonma-yon taqqoslash:
    {"type": "comparison", "title": "...", "left_title": "...", "left_items": ["...", "..."],
     "right_title": "...", "right_items": ["...", "..."]}

QOIDALAR (juda muhim — sifatli, professional natija uchun):
- Bullets qisqa bo'lsin (har biri 12 so'zdan oshmasin), gap emas, fikr sifatida.
- Har bir "content" slaydda 3-5 ta bullet bo'lsin.
- **FORMAT XILMA-XILLIGI SHART**: prezentatsiya faqat "content" va "chart"dan iborat
  bo'lmasin. Kamida 4-5 xil turdagi slaydni aralashtirib ishlat (masalan: content,
  chart, stat, quote, comparison, flowchart — mavzuga mosini tanlab).
- Agar prezentatsiya 6+ slayddan iborat bo'lsa, mantiqiy bo'limlarni "section"
  turi bilan ajrat (masalan: "Muammo" bo'limi, "Yechim" bo'limi, "Natijalar" bo'limi).
- "stat" turini muhim raqamlar/statistika bo'lsa ishlat (masalan bozor hajmi,
  o'sish foizi, foydalanuvchilar soni).
- "quote" turini fikrni kuchaytirish yoki insho uslubida ta'sir qoldirish uchun
  ishlat (mashhur odam, ekspert yoki umumiy hikmatli gap — muallifni ko'rsat).
- "comparison" turini ikkita variant/yondashuv/davr solishtirilganda ishlat.
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
    data = _chat_json(PRESENTATION_SYSTEM_PROMPT, user_prompt, temperature=0.7, max_tokens=6000)

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
