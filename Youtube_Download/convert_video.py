"""
Пакетная конвертация видео в MP4 или AVI (через ffmpeg).

Как запустить:
  python convert_video.py "C:\путь\к\папке\с\видео"
  — либо просто "python convert_video.py" без аргумента, тогда скрипт
  сам спросит путь.

Нужен ffmpeg, установленный отдельно и доступный из PATH (или укажите
полный путь в FFMPEG_PATH ниже). Windows-сборка: https://www.gyan.dev/ffmpeg/builds/

Как это работает:
  1. Сначала пробует БЫСТРЫЙ путь — просто переложить видео/звук в новый
     контейнер без перекодирования (remux, "-c copy"). Работает почти
     мгновенно и без потери качества.
     ВАЖНО: современный ffmpeg довольно охотно упаковывает даже VP9/AV1/
     Opus в .mp4 — remux "успешен" не значит "заработает в старом плеере".
     Контейнер (.mp4/.avi) — это просто обёртка; для реального воспроизведения
     программе/устройству ещё нужно уметь декодировать сам кодек внутри.
     Если цель — гарантированная совместимость со старым софтом/техникой,
     а не просто смена расширения файла, поставьте TRY_FAST_REMUX_FIRST = False
     ниже — тогда всегда будет настоящее перекодирование.
  2. Если remux не удался (или отключён) — перекодирует по-настоящему:
       в MP4: видео → H.264, звук → AAC (максимально совместимо везде)
       в AVI: видео → MPEG-4 part 2, звук → MP3 — старый контейнер AVI
              современные кодеки в принципе не принимает, поэтому для
              него transcode срабатывает всегда, remux пропускается сам
     Перекодирование медленнее и чуть теряет в качестве видео
     (управляется через CRF_MP4 / AVI_BITRATE ниже), зато результат
     гарантированно проигрывается в целевом формате.
  3. Результаты — в папке converted/ рядом со скриптом. Исходники
     открываются только на чтение, ffmpeg сам никогда не пишет в input.
"""

import os
import sys
import subprocess

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "converted")   # всегда рядом со скриптом

TARGET_FORMAT = "mp4"    # "mp4" или "avi"

FFMPEG_PATH = "ffmpeg"   # если ffmpeg не в PATH — укажите полный путь,
                          # например r"C:\tools\ffmpeg\bin\ffmpeg.exe"

TRY_FAST_REMUX_FIRST = True   # если False — сразу перекодирует, без попытки remux

CRF_MP4 = 20        # качество H.264: меньше = лучше и тяжелее (обычно 18-23)
AAC_BITRATE = "192k"

AVI_VIDEO_BITRATE = "4000k"   # у MPEG-4 part 2 нет CRF, задаём битрейт напрямую
MP3_BITRATE = "192k"

VALID_EXTENSIONS = {".webm", ".mkv", ".mp4", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts"}

# =============================================================================


def run_ffmpeg(args: list) -> tuple:
    """Возвращает (успех: bool, stderr_текст: str)."""
    result = subprocess.run(
        [FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True, text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def build_transcode_args(in_path: str, out_path: str) -> list:
    if TARGET_FORMAT == "mp4":
        return [
            "-i", in_path,
            "-c:v", "libx264", "-crf", str(CRF_MP4), "-preset", "medium",
            "-c:a", "aac", "-b:a", AAC_BITRATE,
            out_path,
        ]
    else:  # avi
        return [
            "-i", in_path,
            "-c:v", "mpeg4", "-vtag", "xvid", "-b:v", AVI_VIDEO_BITRATE,
            "-c:a", "libmp3lame", "-b:a", MP3_BITRATE,
            out_path,
        ]


def convert_one(in_path: str, out_path: str) -> tuple:
    """Возвращает (успех, метод: 'remux'|'transcode', сообщение_об_ошибке или None)."""
    if TRY_FAST_REMUX_FIRST:
        ok, err = run_ffmpeg(["-i", in_path, "-c", "copy", out_path])
        if ok:
            return True, "remux", None

    ok, err = run_ffmpeg(build_transcode_args(in_path, out_path))
    if ok:
        return True, "transcode", None
    return False, "transcode", err


def check_ffmpeg_available() -> bool:
    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def resolve_input_dir() -> str:
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = input("Укажите путь к папке с видео: ")
    return os.path.abspath(raw.strip().strip('"').strip("'"))


def process_folder(input_dir: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(input_dir)
                    if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS)

    remuxed, transcoded, errors = [], [], []

    for filename in files:
        in_path = os.path.join(input_dir, filename)
        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(output_dir, f"{base_name}.{TARGET_FORMAT}")

        print(f"Обработка: {filename} ...", end=" ", flush=True)
        ok, method, err = convert_one(in_path, out_path)

        if ok:
            (remuxed if method == "remux" else transcoded).append(filename)
            print("remux (без потерь)" if method == "remux" else "перекодировано")
        else:
            errors.append((filename, err))
            print("ОШИБКА")

    print(f"\nГотово. Быстрый remux: {len(remuxed)}. Перекодировано: {len(transcoded)}.")
    if errors:
        print(f"\n✗ Ошибки ({len(errors)}):")
        for fname, err in errors:
            print(f"   - {fname}: {err.splitlines()[-1] if err else 'неизвестная ошибка'}")


if __name__ == "__main__":
    if TARGET_FORMAT not in ("mp4", "avi"):
        print(f"Ошибка: TARGET_FORMAT должен быть 'mp4' или 'avi', сейчас: {TARGET_FORMAT!r}")
        sys.exit(1)

    if not check_ffmpeg_available():
        print(f"Ошибка: ffmpeg не найден ({FFMPEG_PATH}). "
              f"Установите: https://www.gyan.dev/ffmpeg/builds/ и укажите путь в FFMPEG_PATH, "
              f"либо добавьте папку с ffmpeg.exe в PATH.")
        sys.exit(1)

    input_dir = resolve_input_dir()
    if not os.path.isdir(input_dir):
        print(f"Ошибка: папка не найдена — {input_dir}")
        sys.exit(1)

    if os.path.abspath(input_dir) == os.path.abspath(OUTPUT_DIR):
        print("Ошибка: папка с исходниками совпадает с папкой результатов "
              f"({OUTPUT_DIR}). Работа остановлена, чтобы не задеть исходные файлы.")
        sys.exit(1)

    print(f"Источник:      {input_dir}")
    print(f"Результаты:    {OUTPUT_DIR}")
    print(f"Целевой формат: {TARGET_FORMAT}\n")

    process_folder(input_dir, OUTPUT_DIR)
