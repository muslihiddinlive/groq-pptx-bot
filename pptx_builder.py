"""
Groq'dan kelgan JSON strukturasini haqiqiy .pptx fayliga aylantiradi.
diagrams.py dagi past darajadagi funksiyalarni chaqiradi.
"""
import os
import re
import time

import diagrams as dg
from config import OUTPUT_DIR


def _safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"[\s]+", "_", text)
    return text[:60] or "presentation"


def build_presentation_file(data: dict) -> str:
    """
    :param data: groq_client.generate_presentation() natijasi
    :return: yaratilgan .pptx faylining to'liq yo'li
    """
    prs = dg.new_presentation()

    dg.add_title_slide(prs, data.get("title", "Prezentatsiya"), data.get("subtitle", ""))

    for slide_spec in data.get("slides", []):
        slide_type = slide_spec.get("type")
        title = slide_spec.get("title", "")

        try:
            if slide_type == "content":
                dg.add_bullet_slide(prs, title, slide_spec.get("bullets", []))

            elif slide_type == "chart":
                dg.add_chart_slide(
                    prs, title,
                    slide_spec.get("chart_type", "bar"),
                    slide_spec.get("categories", []),
                    slide_spec.get("series_name", "Ma'lumot"),
                    slide_spec.get("values", []),
                )

            elif slide_type == "flowchart":
                dg.add_flowchart_slide(prs, title, slide_spec.get("steps", []))

            elif slide_type == "orgchart":
                dg.add_orgchart_slide(
                    prs, title,
                    slide_spec.get("root", ""),
                    slide_spec.get("children", []),
                )

            else:
                # noma'lum tur bo'lsa, kontent sifatida ko'rsatamiz (fallback)
                bullets = slide_spec.get("bullets") or [str(slide_spec)]
                dg.add_bullet_slide(prs, title or "Slayd", bullets)

        except Exception as e:  # noqa: BLE001 - bitta slayd xato bersa, hammasi buzilmasin
            dg.add_bullet_slide(prs, title or "Slayd", [f"(Bu slaydni yaratishda xatolik: {e})"])

    filename = f"{_safe_filename(data.get('title', 'prezentatsiya'))}_{int(time.time())}.pptx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    prs.save(filepath)
    return filepath


def build_diagram_file(data: dict) -> str:
    """
    :param data: groq_client.generate_diagram_data() natijasi (bitta diagramma)
    :return: yaratilgan .pptx faylining to'liq yo'li
    """
    prs = dg.new_presentation()
    diagram_type = data.get("diagram_type")
    title = data.get("title", "Diagramma")

    if diagram_type == "chart":
        dg.add_chart_slide(
            prs, title,
            data.get("chart_type", "bar"),
            data.get("categories", []),
            data.get("series_name", "Ma'lumot"),
            data.get("values", []),
        )
    elif diagram_type == "flowchart":
        dg.add_flowchart_slide(prs, title, data.get("steps", []))
    elif diagram_type == "orgchart":
        dg.add_orgchart_slide(prs, title, data.get("root", ""), data.get("children", []))
    elif diagram_type == "venn":
        dg.add_venn_slide(prs, title, data.get("set_a", "A"), data.get("set_b", "B"), data.get("overlap", ""))
    elif diagram_type == "timeline":
        dg.add_timeline_slide(prs, title, data.get("events", []))
    else:
        raise ValueError(f"Noma'lum diagramma turi: {diagram_type}")

    filename = f"diagram_{_safe_filename(title)}_{int(time.time())}.pptx"
    filepath = os.path.join(OUTPUT_DIR, filename)
    prs.save(filepath)
    return filepath
