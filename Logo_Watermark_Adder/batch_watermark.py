"""
Erarta — batch-нанесение логотипа на фото (повторяющийся узор, повёрнутый на угол)

Что делает скрипт:
  1. Берёт SVG-логотип и растрирует его в PNG нужного физического размера (в мм)
     под DPI КАЖДОЙ конкретной фотографии отдельно.
  2. Поворачивает логотип на заданный угол.
  3. Замощает (тайлит) фото повторяющимся логотипом с заданным шагом (в мм),
     начиная от левого верхнего угла.
  4. Сохраняет результат в папку output/, которая создаётся РЯДОМ С ЭТИМ
     ФАЙЛОМ (не зависит от того, откуда запущен скрипт). Исходные фото
     НИКОГДА не открываются на запись и физически не могут быть задеты.
  5. В конце печатает отчёт: сколько файлов обработано и для каких пришлось
     подставить DPI по умолчанию, потому что метаданные файла ненадёжны.

Как запустить:
  python batch_watermark.py "C:\путь\к\папке\с\фото"
  — либо просто "python batch_watermark.py" без аргумента, тогда скрипт
  сам спросит путь к папке с исходниками.

ВАЖНО про DPI (прочитать перед первым запуском на реальных фото):
  Разрешение (DPI), записанное в файле, — это МЕТАДАННЫЕ, а не измерение.
  У очень многих фото с телефона/камеры это поле либо отсутствует, либо
  жёстко прописано в 72 или 96, НЕЗАВИСИМО от реального количества пикселей.
  Такое значение нельзя использовать для перевода миллиметров в пиксели —
  результат будет физически бессмысленным (см. тест ниже: одно и то же
  значение "72" стоит и у настоящего веб-фото, и у 12-мегапиксельного
  телефонного снимка).
  Поэтому скрипт считает DPI из списка {72, 96} ПОДОЗРИТЕЛЬНЫМ и заменяет
  на DEFAULT_DPI, а факт подмены явно печатает в отчёте — чтобы это не
  осталось незамеченным.

Настраиваемые параметры — все внизу, в блоке CONFIG.
"""

import os
import sys
import io
import argparse
from dataclasses import dataclass, field

from PIL import Image
from reportlab.graphics import renderPM
from reportlab.lib.colors import Color
from svglib.svglib import svg2rlg

# ======================= CONFIG (правьте под задачу) =======================

# Папка, где лежит сам этот .py-файл. Все пути ниже привязаны к ней, а не к
# папке, из которой скрипт запущен, — чтобы поведение не зависело от способа
# запуска (двойной клик, bat-файл, запуск из другой директории и т.п.)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_DIR_NAME = "output"                              # имя подпапки с результатами
OUTPUT_DIR = os.path.join(SCRIPT_DIR, OUTPUT_DIR_NAME)  # всегда рядом со скриптом

LOGO_SVG_PATH = os.path.join(SCRIPT_DIR, "logo.svg")    # положите свой логотип
                                                          # рядом со скриптом под этим
                                                          # именем, либо поменяйте путь

ANGLE_DEG = 55          # угол поворота логотипа
SPACING_MM = 35         # шаг узора по X и Y (он же — отступ первого логотипа от угла)
LOGO_WIDTH_MM = 20      # физическая ширина ОДНОГО логотипа в узоре (высота — по пропорциям SVG)
                         # ПРЕДПОЛОЖЕНИЕ: не было указано явно, легко поменять здесь

DEFAULT_DPI = 300                 # чем заменяем ненадёжный/отсутствующий DPI
SUSPICIOUS_DPI_VALUES = {72, 96}  # частые "заглушки", не отражающие реальное разрешение

LOGO_OPACITY = 0.85     # 0..1 — прозрачность узора (1 = полностью непрозрачный)

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}

# =============================================================================


@dataclass
class RunReport:
    processed: list = field(default_factory=list)
    dpi_fallback_used: list = field(default_factory=list)   # (filename, found_dpi)
    errors: list = field(default_factory=list)              # (filename, error_text)


def get_reliable_dpi(img: Image.Image, filename: str, report: RunReport):
    """Возвращает (dpi_x, dpi_y). Если метаданные отсутствуют или подозрительны —
    подставляет DEFAULT_DPI и фиксирует это в отчёте."""
    dpi = img.info.get("dpi")
    if not dpi:
        report.dpi_fallback_used.append((filename, None))
        return DEFAULT_DPI, DEFAULT_DPI

    dpi_x, dpi_y = dpi
    if round(dpi_x) in SUSPICIOUS_DPI_VALUES or round(dpi_y) in SUSPICIOUS_DPI_VALUES:
        report.dpi_fallback_used.append((filename, (round(dpi_x), round(dpi_y))))
        return DEFAULT_DPI, DEFAULT_DPI

    return dpi_x, dpi_y


def mm_to_px(mm: float, dpi: float) -> int:
    return round(mm / 25.4 * dpi)


_logo_cache = {}  # dpi (rounded) -> готовый повёрнутый RGBA-логотип под этот DPI


def get_rotated_logo(dpi: float) -> Image.Image:
    """Растрирует SVG под конкретный DPI (чтобы LOGO_WIDTH_MM был физически верным),
    затем поворачивает. Кэшируется по DPI, чтобы не пересчитывать на каждое фото."""
    key = round(dpi)
    if key in _logo_cache:
        return _logo_cache[key]

    target_width_px = mm_to_px(LOGO_WIDTH_MM, dpi)

    drawing = svg2rlg(LOGO_SVG_PATH)
    native_w, native_h = drawing.width, drawing.height
    scale = target_width_px / native_w
    drawing.width = native_w * scale
    drawing.height = native_h * scale
    drawing.scale(scale, scale)

    buf = io.BytesIO()
    renderPM.drawToFile(drawing, buf, fmt="PNG", bg=Color(0, 0, 0, alpha=0), backendFmt="RGBA")
    buf.seek(0)
    logo_img = Image.open(buf).convert("RGBA")

    if LOGO_OPACITY < 1.0:
        r, g, b, a = logo_img.split()
        a = a.point(lambda v: int(v * LOGO_OPACITY))
        logo_img = Image.merge("RGBA", (r, g, b, a))

    rotated = logo_img.rotate(ANGLE_DEG, expand=True, resample=Image.BICUBIC)
    _logo_cache[key] = rotated
    return rotated


def tile_watermark(photo: Image.Image, dpi_x: float, dpi_y: float) -> Image.Image:
    base = photo.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))

    logo = get_rotated_logo(dpi_x)
    lw, lh = logo.size

    step_x = mm_to_px(SPACING_MM, dpi_x)
    step_y = mm_to_px(SPACING_MM, dpi_y)
    offset_x = step_x   # первый узел узора — тоже в 35мм от угла (см. пояснение в чате)
    offset_y = step_y

    W, H = base.size
    # начинаем на шаг раньше края, чтобы диагональный узор не оставлял пустых
    # клиньев у левого/верхнего края фото
    start_x = offset_x - step_x
    start_y = offset_y - step_y

    y = start_y
    while y < H + lh:
        x = start_x
        while x < W + lw:
            overlay.alpha_composite(logo, dest=(round(x), round(y)))
            x += step_x
        y += step_y

    result = Image.alpha_composite(base, overlay)
    return result


def process_folder(input_dir: str, output_dir: str) -> RunReport:
    report = RunReport()
    os.makedirs(output_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(input_dir)
                    if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS)

    for filename in files:
        in_path = os.path.join(input_dir, filename)
        try:
            with Image.open(in_path) as img:
                original_mode = img.mode
                dpi_x, dpi_y = get_reliable_dpi(img, filename, report)
                watermarked = tile_watermark(img, dpi_x, dpi_y)

                if original_mode != "RGBA":
                    watermarked = watermarked.convert(original_mode) if original_mode in ("RGB", "L") \
                        else watermarked.convert("RGB")

                out_path = os.path.join(output_dir, filename)
                save_kwargs = {}
                ext = os.path.splitext(filename)[1].lower()
                if ext in (".jpg", ".jpeg"):
                    save_kwargs["quality"] = 95
                watermarked.save(out_path, dpi=(dpi_x, dpi_y), **save_kwargs)

                report.processed.append(filename)
        except Exception as e:
            report.errors.append((filename, str(e)))

    return report


def print_report(report: RunReport):
    print(f"\nОбработано файлов: {len(report.processed)}")

    if report.dpi_fallback_used:
        print(f"\n⚠ DPI подставлен по умолчанию ({DEFAULT_DPI}) для {len(report.dpi_fallback_used)} файлов "
              f"— метаданные отсутствовали или были похожи на 'заглушку':")
        for fname, found in report.dpi_fallback_used:
            found_str = "нет DPI-метаданных" if found is None else f"в файле указано {found}"
            print(f"   - {fname}: {found_str}")

    if report.errors:
        print(f"\n✗ Ошибки при обработке ({len(report.errors)}):")
        for fname, err in report.errors:
            print(f"   - {fname}: {err}")

    if not report.dpi_fallback_used and not report.errors:
        print("Замечаний нет — DPI везде читался из метаданных надёжно.")


def resolve_input_dir() -> str:
    parser = argparse.ArgumentParser(
        description="Наносит повторяющийся повёрнутый логотип-узор на фото из указанной папки."
    )
    parser.add_argument(
        "input_dir", nargs="?", default=None,
        help="Путь к папке с исходными фото. Если не указан — скрипт спросит его сам."
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    if not input_dir:
        input_dir = input("Укажите путь к папке с исходными фото: ")

    # на случай, если путь скопирован из проводника Windows в кавычках
    input_dir = input_dir.strip().strip('"').strip("'")
    return os.path.abspath(input_dir)


if __name__ == "__main__":
    input_dir = resolve_input_dir()

    if not os.path.isdir(input_dir):
        print(f"Ошибка: папка не найдена — {input_dir}")
        sys.exit(1)

    if os.path.abspath(input_dir) == os.path.abspath(OUTPUT_DIR):
        print("Ошибка: папка с исходниками совпадает с папкой результатов "
              f"({OUTPUT_DIR}). Работа остановлена, чтобы не задеть исходные файлы.")
        sys.exit(1)

    if not os.path.isfile(LOGO_SVG_PATH):
        print(f"Ошибка: SVG-логотип не найден — {LOGO_SVG_PATH}\n"
              f"Положите файл логотипа рядом со скриптом (см. LOGO_SVG_PATH в CONFIG).")
        sys.exit(1)

    print(f"Источник:   {input_dir}")
    print(f"Результаты: {OUTPUT_DIR}\n")

    rep = process_folder(input_dir, OUTPUT_DIR)
    print_report(rep)
