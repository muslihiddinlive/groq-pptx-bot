"""
Fayl-yordamchi rejimi — ms-file-toolkit (DOCX/XLSX/PPTX/PDF o'qish-yozish)ni
Groq'ning function-calling (tool-use) imkoniyati orqali botga ulaydi.

Groq Chat Completions API OpenAI bilan mos (`tools=[{"type": "function", ...}]`,
`response.choices[0].message.tool_calls`), shuning uchun ms_toolkit.TOOLS
(Anthropic uslubidagi `input_schema`) ni shu formatga o'giramiz.

Har bir foydalanuvchi uchun alohida papka (`MS_TOOLKIT_BASE_DIR` o'rnida
`dispatch(..., base_dir=...)`) ishlatiladi — shu orqali bir foydalanuvchi
boshqasining fayllariga tegina olmaydi.
"""
import json
import logging
import os

from groq import Groq

from ms_toolkit import TOOLS, dispatch
from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

# Har bir foydalanuvchining fayllari shu asosiy papka ostida, alohida
# ID papkasida saqlanadi: generated_files/file_assistant/<user_id>/
FILE_ASSISTANT_ROOT = os.path.join(os.getenv("OUTPUT_DIR", "generated_files"), "file_assistant")

# Bitta so'rovda AI nechta marta ketma-ket tool chaqirishi mumkinligi
# (cheksiz aylanib qolmasligi uchun chegara).
MAX_TOOL_ITERATIONS = 8

# Suhbat tarixida saqlanadigan oxirgi necha xabar (juda uzun bo'lib ketmasligi uchun)
MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """Siz Microsoft Word/Excel/PowerPoint va PDF fayllar bilan ishlaydigan
yordamchisiz. Foydalanuvchi fayl yuborishi yoki fayl haqida so'rashi mumkin — mos
tool'ni chaqirib bajaring.

Qoidalar:
- Fayllar bilan ishlaganda faqat foydalanuvchi yuborgan yoki siz o'zingiz yaratgan
  fayl nomlaridan foydalaning (aniq to'liq yo'l shart emas — fayl nomi yetarli,
  tizim uni avtomatik topadi).
- Agar foydalanuvchi fayl yuklamasdan "shunday hujjat/jadval/taqdimot yarat" desa,
  yangi fayl nomi tanlang (masalan 'hisobot.docx') va uni yarating.
- Xato yuz bersa (masalan fayl topilmadi), buni foydalanuvchiga tushunarli tilda
  tushuntiring, texnik tafsilotlarni ko'p yozmang.
- Javobni har doim o'zbek tilida bering."""


class FileAssistantError(Exception):
    """Groq bilan ishlashda yoki tool ishlatishda kutilmagan xatolik."""


def _user_dir(user_id: int) -> str:
    path = os.path.join(FILE_ASSISTANT_ROOT, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _resolve_filename(user_dir: str, name: str) -> str:
    """AI berilgan fayl nomini (masalan 'hisobot.docx') foydalanuvchi
    papkasidagi to'liq yo'lga aylantiradi — agar allaqachon to'liq yo'l
    bo'lsa (papka nomi bilan boshlansa), o'zgartirmaydi."""
    if os.path.isabs(name) or name.startswith(user_dir):
        return name
    return os.path.join(user_dir, os.path.basename(name))


def _tools_for_groq() -> list[dict]:
    """ms_toolkit.TOOLS (Anthropic input_schema) -> Groq/OpenAI function-calling formati."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOLS
    ]


_GROQ_TOOLS = _tools_for_groq()


def save_uploaded_file(user_id: int, local_tmp_path: str, original_filename: str) -> str:
    """Telegram'dan yuklab olingan faylni foydalanuvchi papkasiga ko'chiradi,
    yangi (doimiy) yo'lini qaytaradi."""
    user_dir = _user_dir(user_id)
    dest = os.path.join(user_dir, original_filename)
    os.replace(local_tmp_path, dest)
    return dest


def run_file_assistant(user_id: int, history: list[dict], user_message: str) -> tuple[str, list[str]]:
    """
    Bitta foydalanuvchi xabarini AI'ga yuboradi, kerakli tool'larni ishga
    tushiradi, va (matnli javob, yaratilgan/o'zgartirilgan fayllar ro'yxati)
    qaytaradi.

    :param user_id: Telegram user_id (fayllarni ajratish uchun)
    :param history: oldingi xabarlar [{"role": "user"/"assistant", "content": "..."}]
    :param user_message: foydalanuvchining yangi xabari
    """
    if not GROQ_API_KEYS:
        raise FileAssistantError(
            "Hech qanday Groq API kaliti sozlanmagan. .env fayliga GROQ_API_KEYS qo'shing."
        )

    user_dir = _user_dir(user_id)
    client = Groq(api_key=GROQ_API_KEYS[0])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-MAX_HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": user_message})

    touched_files: dict[str, str] = {}  # file_path -> oxirgi status

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=_GROQ_TOOLS,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as e:  # noqa: BLE001 - Groq/tarmoq xatolari
            raise FileAssistantError(f"Groq bilan bog'lanishda xatolik: {e}") from e

        choice = completion.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            # Yakuniy matnli javob — tsikl tugaydi.
            final_text = msg.content or "Bajarildi."
            return final_text, list(touched_files.keys())

        # Assistant xabarini (tool_calls bilan) tarixga qo'shamiz.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_input = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_input = {}

            # AI odatda faqat fayl NOMINI beradi — uni foydalanuvchi papkasidagi
            # to'liq yo'lga aylantiramiz, keyin dispatch() xavfsizlik tekshiruvini
            # shu papka bilan cheklab (base_dir) yana bir bor tasdiqlaydi.
            for path_key in ("file_path", "image_path", "save_as", "output_path", "output_dir"):
                if path_key in tool_input and tool_input[path_key]:
                    tool_input[path_key] = _resolve_filename(user_dir, tool_input[path_key])
            if "file_paths" in tool_input and isinstance(tool_input["file_paths"], list):
                tool_input["file_paths"] = [_resolve_filename(user_dir, p) for p in tool_input["file_paths"]]

            result = dispatch(tool_name, tool_input, base_dir=user_dir)
            logger.info("file_assistant tool=%s user=%s -> %s", tool_name, user_id,
                        "OK" if "error" not in result else f"ERROR: {result['error']}")

            if "error" not in result and "file_path" in result and "status" in result:
                touched_files[result["file_path"]] = result["status"]
            # merge_pdfs/split_pdf natijasi output_path/output_files'da bo'lishi mumkin
            if "error" not in result:
                if "output_path" in result:
                    touched_files[result["output_path"]] = result.get("status", "created")
                if isinstance(result.get("output_files"), list):
                    for f in result["output_files"]:
                        touched_files[f] = "created"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    raise FileAssistantError(
        f"{MAX_TOOL_ITERATIONS} marta urinishdan keyin ham AI yakuniy javob bermadi."
    )
