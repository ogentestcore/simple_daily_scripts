"""
Транскрибация видео/аудио в субтитры (SRT) через faster-whisper.

Как запустить:
  python transcribe_subtitles.py "C:\путь\к\файлу_или_папке"
  — либо просто "python transcribe_subtitles.py" без аргумента, тогда
  скрипт спросит путь. Можно указать как один файл, так и папку
  (тогда обработает все видео/аудио файлы внутри).

Один раз установить:
  pip install faster-whisper

Про модели (WHISPER_MODEL_SIZE ниже) — компромисс качество/скорость:
  tiny/base/small — быстро, но чаще ошибается, особенно на неанглийских
                    языках и в шумных записях
  medium          — разумный баланс для большинства задач
  large-v3        — лучшее качество, но заметно медленнее и требует больше
                    памяти; рекомендую именно её для японского/испанского/
                    французского, если позволяет железо

DEVICE = "cpu" по умолчанию — работает везде, но медленно на large-моделях.
Если есть NVIDIA-видеокарта с CUDA — поставьте DEVICE = "cuda",
COMPUTE_TYPE = "float16", будет ощутимо быстрее.
"""

import os
import sys

from faster_whisper import WhisperModel

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "subtitles")   # всегда рядом со скриптом

WHISPER_MODEL_SIZE = "medium"   # tiny / base / small / medium / large-v3
DEVICE = "cpu"                  # "cpu" или "cuda"
COMPUTE_TYPE = "int8"           # "int8" для cpu, "float16" для cuda — см. пояснение выше

LANGUAGE = None   # None = автоопределение языка. Либо код: "ja", "es", "fr", "ru"...
                   # Явное указание чуть точнее и быстрее, если язык заранее известен.

VALID_EXTENSIONS = {".mp4", ".webm", ".avi", ".mkv", ".mov", ".wav", ".mp3", ".m4a", ".flac"}

# =============================================================================


def format_timestamp(seconds: float) -> str:
    """Секунды -> формат SRT: ЧЧ:ММ:СС,ммм"""
    ms_total = round(seconds * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def transcribe_to_srt(model: WhisperModel, media_path: str, srt_path: str) -> str:
    """Транскрибирует файл, пишет .srt, возвращает определённый язык."""
    segments, info = model.transcribe(media_path, language=LANGUAGE, vad_filter=True)

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")

    return info.language


def resolve_input_path() -> str:
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = input("Укажите путь к файлу или папке с видео/аудио: ")
    return os.path.abspath(raw.strip().strip('"').strip("'"))


def collect_media_files(input_path: str) -> list:
    if os.path.isfile(input_path):
        return [input_path]
    return [
        os.path.join(input_path, f) for f in sorted(os.listdir(input_path))
        if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS
    ]


if __name__ == "__main__":
    input_path = resolve_input_path()

    if not os.path.exists(input_path):
        print(f"Ошибка: не найдено — {input_path}")
        sys.exit(1)

    if os.path.isdir(input_path) and os.path.abspath(input_path) == os.path.abspath(OUTPUT_DIR):
        print(f"Ошибка: папка-источник совпадает с папкой результатов ({OUTPUT_DIR}). Остановлено.")
        sys.exit(1)

    media_files = collect_media_files(input_path)
    if not media_files:
        print("Не найдено подходящих файлов для транскрибации.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Модель: {WHISPER_MODEL_SIZE} ({DEVICE}, {COMPUTE_TYPE})")
    print(f"Файлов к обработке: {len(media_files)}\n")

    print("Загружаю модель Whisper (при первом запуске скачается автоматически)...")
    model = WhisperModel(WHISPER_MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

    processed, errors = [], []
    for media_path in media_files:
        filename = os.path.basename(media_path)
        base_name = os.path.splitext(filename)[0]
        srt_path = os.path.join(OUTPUT_DIR, f"{base_name}.srt")

        print(f"Транскрибация: {filename} ...", end=" ", flush=True)
        try:
            detected_lang = transcribe_to_srt(model, media_path, srt_path)
            print(f"готово (язык: {detected_lang})")
            processed.append(filename)
        except Exception as e:
            print("ОШИБКА")
            errors.append((filename, str(e)))

    print(f"\nГотово. Обработано: {len(processed)}. Результаты — в {OUTPUT_DIR}")
    if errors:
        print(f"\n✗ Ошибки ({len(errors)}):")
        for fname, err in errors:
            print(f"   - {fname}: {err}")
