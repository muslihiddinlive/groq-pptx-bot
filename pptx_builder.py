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
    brand = data.get("title", "")

    dg.add_title_slide(prs, data.get("title", "Prezentatsiya"), data.get("subtitle", ""))

    all_slides = data.get("slides", [])
    total = len(all_slides) + 1  # +1 title slide uchun
    created_slides = []  # (slide, is_title) — footer qo'shish uchun

    for slide_spec in all_slides:
        slide_type = slide_spec.get("type")
        title = slide_spec.get("title", "")

        try:
            if slide_type == "content":
                slide = dg.add_bullet_slide(prs, title, slide_spec.get("bullets", []))

            elif slide_type == "chart":
                slide = dg.add_chart_slide(
                    prs, title,
                    slide_spec.get("chart_type", "bar"),
                    slide_spec.get("categories", []),
                    slide_spec.get("series_name", "Ma'lumot"),
                    slide_spec.get("values", []),
                )

            elif slide_type == "flowchart":
                slide = dg.add_flowchart_slide(prs, title, slide_spec.get("steps", []))

            elif slide_type == "orgchart":
                slide = dg.add_orgchart_slide(
                    prs, title,
                    slide_spec.get("root", ""),
                    slide_spec.get("children", []),
                )

            elif slide_type == "venn":
                slide = dg.add_venn_slide(
                    prs, title,
                    slide_spec.get("set_a", "A"), slide_spec.get("set_b", "B"),
                    slide_spec.get("overlap", ""),
                )

            elif slide_type == "timeline":
                slide = dg.add_timeline_slide(prs, title, slide_spec.get("events", []))

            elif slide_type == "section":
                slide = dg.add_section_slide(prs, title, slide_spec.get("subtitle", ""))

            elif slide_type == "stat":
                slide = dg.add_stat_slide(prs, title, slide_spec.get("stats", []))

            elif slide_type == "quote":
                slide = dg.add_quote_slide(prs, slide_spec.get("quote", ""), slide_spec.get("author", ""))

            elif slide_type == "comparison":
                slide = dg.add_comparison_slide(
                    prs, title,
                    slide_spec.get("left_title", ""), slide_spec.get("left_items", []),
                    slide_spec.get("right_title", ""), slide_spec.get("right_items", []),
                )

            else:
                # noma'lum tur bo'lsa, kontent sifatida ko'rsatamiz (fallback)
                bullets = slide_spec.get("bullets") or [str(slide_spec)]
                slide = dg.add_bullet_slide(prs, title or "Slayd", bullets)

            created_slides.append(slide)

        except Exception as e:  # noqa: BLE001 - bitta slayd xato bersa, hammasi buzilmasin
            created_slides.append(dg.add_bullet_slide(prs, title or "Slayd", [f"(Bu slaydni yaratishda xatolik: {e})"]))

    # Har bir slaydga (title slide bundan mustasno) sahifa raqamini qo'shamiz
    for i, slide in enumerate(created_slides, start=2):
        dg.add_footer(slide, i, total, brand)

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
