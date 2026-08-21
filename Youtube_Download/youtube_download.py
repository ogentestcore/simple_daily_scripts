"""
Скачивание видео с YouTube через yt-dlp.

Как запустить:
  python youtube_download.py "https://www.youtube.com/watch?v=..."
  — либо просто "python youtube_download.py" без аргумента, тогда скрипт
  сам спросит ссылку.

Один раз установить зависимости:
  pip install -U "yt-dlp[default]"
  (именно [default], а не голый "yt-dlp" — иначе не установится yt-dlp-ejs,
   без которого YouTube с середины 2026 года просто не отдаёт видео, см. ниже)

ВАЖНО — YouTube требует JavaScript-рантайм (актуально на август 2026):
  С недавних пор YouTube проверяет, что скачивающий может выполнить
  JS-задачку («JS challenge»), прежде чем отдать ссылку на сам видеофайл.
  Без установленного JS-рантайма yt-dlp получает только урезанный список
  форматов (например, старый низкокачественный формат 18) — и даже его
  YouTube иногда отдаёт с ошибкой 403 Forbidden, как в вашем случае.

  Решение — установить Deno (рекомендованный yt-dlp JS-рантайм):
    1. Скачать с https://github.com/denoland/deno/releases/latest
       (для Windows — архив deno-x86_64-pc-windows-msvc.zip)
    2. Распаковать, внутри будет deno.exe
    3. Указать путь к нему в DENO_PATH ниже в CONFIG — тогда ничего
       больше не нужно, PATH трогать не придётся.
       (Альтернативно можно добавить папку с deno.exe в системный PATH —
       тогда DENO_PATH можно оставить пустым, yt-dlp найдёт deno сам.)

Для режима MODE = "best" (максимальное качество) дополнительно нужен ffmpeg —
он СКЛЕИВАЕТ отдельные видео- и аудио-дорожки (у YouTube лучшее качество почти
всегда лежит раздельно). Без ffmpeg используйте MODE = "simple" — скрипт
скачает лучший вариант, где видео и звук уже объединены в один файл
(качество чуть ниже, зато работает без доп. установок).

Ffmpeg на Windows: https://www.gyan.dev/ffmpeg/builds/ (скачать build,
распаковать, путь до папки bin добавить в PATH).

Ответственное использование: скачивайте только то, на что у вас есть права —
собственные видео, ролики с открытой лицензией (Creative Commons и т.п.)
или контент, который правообладатель явно разрешает сохранять. Массовое
скачивание чужих защищённых авторским правом видео может нарушать условия
использования YouTube и законодательство об авторском праве.
"""

import os
import sys

from yt_dlp import YoutubeDL

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "downloads")  # всегда рядом со скриптом

# "simple" — лучший вариант с уже объединёнными видео+звук, ffmpeg не нужен
# "best"   — максимальное качество, отдельные дорожки СКЛЕИВАЮТСЯ ffmpeg'ом
# "audio"  — только звук, сохраняется как mp3 (тоже нужен ffmpeg)
MODE = "simple"

# Путь к deno.exe, если он НЕ добавлен в системный PATH. Оставьте пустой
# строкой, если deno уже доступен из PATH — yt-dlp найдёт его сам.
DENO_PATH = ""  # например: r"C:\tools\deno\deno.exe"

# Контейнер для склеенного файла при раздельных видео/звук потоках.
# "" (пусто)  — решает yt-dlp сам: подбирает контейнер, который умеет
#               и видео-, и аудиокодек без переконвертации (см. пояснение
#               в чате — из-за этого иногда получается .webm вместо .mp4,
#               если звук в формате Opus).
# "mp4"       — принудительно .mp4. Аудиопоток при этом НЕ перекодируется
#               (остаётся тем же кодеком, например Opus), просто упаковывается
#               в mp4-контейнер. Играет в VLC/mpv/современных браузерах,
#               но не гарантированно — в старом ПО и части устройств
#               Opus-в-mp4 не поддерживается.
MERGE_OUTPUT_FORMAT = ""

# =============================================================================


FORMAT_BY_MODE = {
    "simple": None,                        # см. пояснение ниже
    "best": "bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}
# "simple": специально НЕ задаём формат явно — пусть решает сам yt-dlp.
#   У него встроенная логика: если ffmpeg найден — берёт максимальное
#   качество и сам склеивает; если не найден — уступает и берёт лучший
#   уже смешанный (video+audio в одном потоке) вариант, если такой есть.
#   Раньше здесь было жёстко прописано "best" — из-за этого скрипт
#   падал с "Requested format is not available" на видео, для которых
#   YouTube вообще не отдаёт единый файл (только раздельные HLS-потоки,
#   такое всё чаще встречается, особенно у "миксов"/автоплейлистов).
#   Если ffmpeg не установлен, а видео отдаётся ТОЛЬКО раздельными
#   потоками — скачать его без ffmpeg физически невозможно, тут уже
#   не вопрос настройки скрипта.


def build_options() -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    opts = {
        "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
        "noplaylist": True,   # скачивать только указанное видео, не весь плейлист
    }

    fmt = FORMAT_BY_MODE[MODE]
    if fmt:
        opts["format"] = fmt

    if MERGE_OUTPUT_FORMAT:
        opts["merge_output_format"] = MERGE_OUTPUT_FORMAT

    if DENO_PATH:
        opts["js_runtimes"] = {"deno": {"path": DENO_PATH}}

    if MODE == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    return opts


def resolve_url() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1].strip().strip('"').strip("'")
    return input("Укажите ссылку на видео YouTube: ").strip().strip('"').strip("'")


if __name__ == "__main__":
    url = resolve_url()
    if not url:
        print("Ссылка не указана.")
        sys.exit(1)

    print(f"Режим:      {MODE}")
    print(f"Результаты: {OUTPUT_DIR}\n")

    try:
        with YoutubeDL(build_options()) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"Ошибка при скачивании: {e}")
        sys.exit(1)
