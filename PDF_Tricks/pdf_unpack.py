#!/usr/bin/env python3
"""
pdf_unpack.py — разбор вёрстки PDF на редактируемые составляющие.

Что делает:
  1) экспортирует каждую страницу в SVG, сохраняя текст текстом (не кривыми)
  2) вытаскивает все растровые картинки в оригинальном разрешении
  3) считает эффективное ppi каждой картинки на месте вставки
  4) собирает layout_spec.json — координаты, шрифты, кегли, цвета в миллиметрах

Использование:
    pip install pymupdf
    python3 pdf_unpack.py input.pdf -o out/

Требования: Python 3.9+, PyMuPDF >= 1.23
"""

import argparse
import json
import os
import sys
from collections import Counter

try:
    import pymupdf
except ImportError:
    sys.exit("Нужен PyMuPDF:  pip install pymupdf")

PT_TO_MM = 25.4 / 72.0


def mm(v, nd=1):
    """Пункты PDF -> миллиметры."""
    return round(v * PT_TO_MM, nd)


def int_to_hex(color_int):
    """PyMuPDF отдаёт цвет спана как int 0xRRGGBB."""
    return f"#{color_int:06x}"


def unpack(pdf_path, outdir, text_as_path=False, dpi_preview=0):
    doc = pymupdf.open(pdf_path)

    svg_dir = os.path.join(outdir, "svg")
    img_dir = os.path.join(outdir, "images")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(img_dir, exist_ok=True)
    if dpi_preview:
        png_dir = os.path.join(outdir, "preview")
        os.makedirs(png_dir, exist_ok=True)

    spec = {
        "source": os.path.basename(pdf_path),
        "producer": doc.metadata.get("producer"),
        "creator": doc.metadata.get("creator"),
        "created": doc.metadata.get("creationDate"),
        "page_count": doc.page_count,
        "units": "mm, origin = top-left of the page",
        "pages": [],
    }

    saved_xrefs = set()
    font_tally = Counter()

    for idx, page in enumerate(doc, start=1):
        # --- 1. SVG ---------------------------------------------------------
        svg = page.get_svg_image(text_as_path=text_as_path)
        svg_name = f"page_{idx:02d}.svg"
        with open(os.path.join(svg_dir, svg_name), "w", encoding="utf-8") as fh:
            fh.write(svg)

        # --- optional raster preview ---------------------------------------
        if dpi_preview:
            page.get_pixmap(dpi=dpi_preview).save(
                os.path.join(png_dir, f"page_{idx:02d}.png")
            )

        rect = page.rect
        pg = {
            "page": idx,
            "size_mm": [mm(rect.width), mm(rect.height)],
            "rotation": page.rotation,
            "svg": f"svg/{svg_name}",
            "vector_path_count": len(page.get_drawings()),
            "images": [],
            "text_blocks": [],
        }

        # --- 2 + 3. картинки и их реальное разрешение -----------------------
        for info_tuple in page.get_images(full=True):
            xref = info_tuple[0]
            img = doc.extract_image(xref)  # оригинальные байты, без пережатия
            fname = f"p{idx:02d}_x{xref}.{img['ext']}"
            if xref not in saved_xrefs:
                with open(os.path.join(img_dir, fname), "wb") as fh:
                    fh.write(img["image"])
                saved_xrefs.add(xref)

            # одна и та же картинка может быть вставлена несколько раз
            for r in page.get_image_rects(xref):
                placed_in = r.width / 72.0  # ширина на макете в дюймах
                pg["images"].append(
                    {
                        "file": f"images/{fname}",
                        "xref": xref,
                        "pixels": [img["width"], img["height"]],
                        "placed_mm": [mm(r.width), mm(r.height)],
                        "xy_mm": [mm(r.x0), mm(r.y0)],
                        "effective_ppi": round(img["width"] / placed_in) if placed_in else None,
                        "colorspace": img.get("colorspace"),
                        "has_alpha": bool(img.get("smask")),
                    }
                )

        # --- 4. текст с координатами ---------------------------------------
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:  # 0 = текст, 1 = картинка
                continue
            x0, y0, x1, y1 = block["bbox"]
            lines = []
            for line in block["lines"]:
                spans = [
                    {
                        "text": s["text"],
                        "font": s["font"],
                        "size_pt": round(s["size"], 2),
                        "color": int_to_hex(s["color"]),
                        "bbox_mm": [mm(v) for v in s["bbox"]],
                    }
                    for s in line["spans"]
                ]
                for s in line["spans"]:
                    font_tally[s["font"]] += len(s["text"])
                lines.append(
                    {
                        "baseline_dir": line["dir"],  # (1,0) = горизонтально
                        "bbox_mm": [mm(v) for v in line["bbox"]],
                        "spans": spans,
                    }
                )
            pg["text_blocks"].append(
                {
                    "bbox_mm": [mm(x0), mm(y0), mm(x1), mm(y1)],
                    "width_mm": mm(x1 - x0),
                    "height_mm": mm(y1 - y0),
                    "plain_text": "\n".join(
                        "".join(s["text"] for s in ln["spans"]) for ln in lines
                    ),
                    "lines": lines,
                }
            )

        spec["pages"].append(pg)

    spec["font_usage_chars"] = dict(font_tally.most_common())

    with open(os.path.join(outdir, "layout_spec.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)

    doc.close()
    return spec


def main():
    ap = argparse.ArgumentParser(description="Разбор PDF-вёрстки на SVG + картинки + координаты")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="out", help="папка для результатов")
    ap.add_argument("--text-as-path", action="store_true",
                    help="перевести текст в кривые (по умолчанию НЕТ — текст остаётся текстом)")
    ap.add_argument("--preview-dpi", type=int, default=0,
                    help="дополнительно отрендерить PNG-превью, например 150")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    spec = unpack(a.pdf, a.out, a.text_as_path, a.preview_dpi)

    print(f"{spec['source']}: {spec['page_count']} стр., создано в {spec['creator']}")
    for p in spec["pages"]:
        low = [i for i in p["images"] if (i["effective_ppi"] or 999) < 220]
        flag = f"  ⚠ низкое ppi: {[i['effective_ppi'] for i in low]}" if low else ""
        print(
            f"  стр.{p['page']:>2}  {p['size_mm'][0]}×{p['size_mm'][1]} мм  "
            f"текст.блоков={len(p['text_blocks']):<3} контуров={p['vector_path_count']:<4} "
            f"картинок={len(p['images'])}{flag}"
        )
    print("\nШрифты (символов):")
    for f, n in spec["font_usage_chars"].items():
        print(f"  {f:<32} {n}")
    print(f"\nГотово -> {a.out}/")


if __name__ == "__main__":
    main()
