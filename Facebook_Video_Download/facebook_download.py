"""
Скачивание видео с Facebook через yt-dlp.

Отдельный скрипт от youtube_download.py — сделано намеренно: у Facebook
другая логика авторизации (нужны куки для части видео) и заметно менее
стабильный экстрактор (Meta часто меняет разметку страниц, из-за чего
yt-dlp периодически ломается именно на Facebook, независимо от YouTube).

Как запустить:
  Одна ссылка:
    python facebook_download.py "https://www.facebook.com/watch?v=..."

  Пакетно, по списку ссылок из файла:
    python facebook_download.py links.txt
    python facebook_download.py links.docx

  Без аргумента — скрипт спросит сам (ссылку или путь к файлу).

Один раз установить зависимости:
  pip install -U "yt-dlp[default]"
  pip install python-docx        # нужно только для batch-режима из .docx

Формат файла со ссылками:
  .txt   — по одной ссылке на строку; строки, начинающиеся с "#", и
           пустые строки игнорируются.
  .docx  — вытаскиваются ОБА варианта: обычные URL, напечатанные текстом,
           и настоящие гиперссылки (когда текст ссылки не совпадает с
           самим URL, например ссылка спрятана под словом "смотреть").

Публичные и приватные видео — разница принципиальная:
  Публичный пост/видео обычно скачивается без какой-либо авторизации.
  Приватное видео, видео "только для друзей" или с возрастным ограничением
  yt-dlp скачать без входа в аккаунт не сможет — нужно передать куки
  залогиненной сессии одним из двух способов (см. CONFIG ниже):
    - COOKIES_FROM_BROWSER — yt-dlp сам достанет куки из указанного
      браузера (нужно быть залогиненным в Facebook именно в нём);
    - COOKIES_FILE — путь к экспортированному cookies.txt (формат Netscape,
      экспортируется расширением браузера вроде "Get cookies.txt").
  Если ролики, которые вам нужны, публичные — ничего из этого настраивать
  не нужно, оставьте оба поля пустыми.

В отличие от youtube_download.py, JS-рантайм (Deno) для Facebook сейчас
не требуется — это специфика именно антибот-системы YouTube.

Facebook-экстрактор в yt-dlp ломается чаще, чем youtube-экстрактор:
Meta регулярно меняет вёрстку страниц, и через какое-то время скрипт может
начать падать с ошибками вида "Cannot parse data" или "No video formats
found" даже на видео, которые раньше скачивались без проблем. Первое, что
стоит делать при такой ошибке — обновить yt-dlp (pip install -U yt-dlp) и
повторить попытку; если не помогло — проблема на стороне экстрактора, и
нужно ждать фикса от разработчиков yt-dlp.

На 22.09.2026 именно так и обстоит дело с "Cannot parse data" на ссылках
вида facebook.com/reel/<id> — это открытый и пока НЕ исправленный баг
самого yt-dlp (issue #17704 в репозитории yt-dlp/yt-dlp, заведён 20.09.2026),
не связанный ни с этим скриптом, ни с вашими куками. Судя по истории похожих
багов (например, #7469), разработчики обычно чинят такое за несколько дней
после репорта. Пока фикса нет, скрипт при сбое на /reel/ ссылке автоматически
пробует ту же самую ссылку в двух альтернативных форматах (facebook.com/watch/
и mbasic.facebook.com) — иногда это использует другой, ещё не сломанный путь
в экстракторе, но гарантии нет: если сломан сам парсинг данных видео, а не
конкретно "reel"-обёртка, не поможет и это.

Ошибка "unable to open for writing: [Errno 2] No such file or directory" на
части ссылок — это не сбой конкретного видео, а слишком длинное имя файла:
у Facebook названием видео обычно становится весь текст поста, и если пост
длинный, итоговое имя файла превышает предел файловой системы (в Windows —
предел длины всего ПУТИ). Решается настройкой TRIM_FILENAME_LENGTH в CONFIG
ниже — она уже включена по умолчанию. На тех же "reel"-ссылках, где парсинг
данных сломан (см. абзац выше), возможен и другой вариант той же по сути
ошибки: экстрактор не может найти настоящую подпись к видео и вместо неё
подставляет случайный текст со страницы (например, счётчик просмотров) —
такой "суррогатный" заголовок иногда тоже не проходит как валидное имя файла.

Batch-режим не падает на первой ошибке: для каждого неудачного видео
записывается причина, а после прогона в OUTPUT_DIR появляются два файла:
  failed_links_details.txt — ссылка + текст ошибки, для диагностики;
  failed_links_retry.txt   — те же ссылки, но уже готовые для повторного
                              запуска этим же скриптом (просто ссылки, по
                              одной на строку) — удобно, если ошибка была
                              временной (см. про баг экстрактора выше) и вы
                              захотите повторить попытку позже.

Для режима MODE = "best" нужен ffmpeg (склейка отдельных видео/аудио
потоков) — см. пояснения в youtube_download.py, они актуальны и здесь.

Ответственное использование: скачивайте только то, на что у вас есть права
или явное разрешение правообладателя. Массовое скачивание чужого защищённого
авторским правом контента может нарушать условия использования Facebook и
законодательство об авторском праве.
"""

import os
import re
import sys
import time

from yt_dlp import YoutubeDL

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "downloads")  # всегда рядом со скриптом

# "simple" — лучший вариант с уже объединёнными видео+звук, ffmpeg не нужен
# "best"   — максимальное качество, отдельные дорожки СКЛЕИВАЮТСЯ ffmpeg'ом
# "audio"  — только звук, сохраняется как mp3 (тоже нужен ffmpeg)
MODE = "simple"

# Куки для приватных/ограниченных видео. Достаточно заполнить ОДНО поле,
# оставьте оба пустыми, если качаете только публичные видео.
COOKIES_FROM_BROWSER = ""  # "chrome" / "firefox" / "edge" и т.п.
COOKIES_FILE = ""          # путь к экспортированному cookies.txt

# Контейнер для склеенного файла при раздельных видео/звук потоках.
# "" — решает yt-dlp сам (см. подробное пояснение в youtube_download.py).
MERGE_OUTPUT_FORMAT = ""

# Пауза между роликами в batch-режиме (секунды) — снижает риск рейт-лимита
# со стороны Facebook при обработке длинного списка ссылок подряд.
DELAY_BETWEEN_DOWNLOADS_SEC = 2

# У Facebook названием видео нередко служит весь текст поста — на некоторых
# роликах это даёт имя файла длиннее, чем допускает файловая система (в
# частности, предел длины ПУТИ в Windows), и скачивание падает с ошибкой
# "unable to open for writing: ... No such file or directory". Ниже — сколько
# символов имени файла (без расширения и без "[id]") оставлять максимум.
# Если OUTPUT_DIR у вас сам по себе очень длинный (глубоко вложенная папка,
# синхронизируемая через OneDrive и т.п.) — уменьшите это число.
TRIM_FILENAME_LENGTH = 100

# =============================================================================


FORMAT_BY_MODE = {
    "simple": None,
    "best": "bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}


def build_options() -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    opts = {
        # id добавлен в шаблон имени файла намеренно: у Facebook разные
        # ролики нередко получают одинаковый или пустой title (особенно
        # Reels), и без id повторный batch-запуск будет перезаписывать
        # уже скачанные файлы друг другом.
        "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "trim_file_name": TRIM_FILENAME_LENGTH,  # чинит "No such file or directory" на длинных подписях FB
        "windowsfilenames": True,  # заменяет символы, недопустимые в Windows, на безопасные аналоги
    }

    fmt = FORMAT_BY_MODE[MODE]
    if fmt:
        opts["format"] = fmt

    if MERGE_OUTPUT_FORMAT:
        opts["merge_output_format"] = MERGE_OUTPUT_FORMAT

    if COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    elif COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    if MODE == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    return opts


def extract_urls_from_txt(path: str) -> list:
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def extract_urls_from_docx(path: str) -> list:
    try:
        from docx import Document
    except ImportError:
        print("Для чтения .docx нужна библиотека: pip install python-docx")
        sys.exit(1)

    doc = Document(path)
    urls = []
    seen = set()

    # 1. Настоящие гиперссылки (текст ссылки может не совпадать с URL)
    for rel in doc.part.rels.values():
        target = getattr(rel, "target_ref", "")
        if "hyperlink" in rel.reltype and target.startswith("http") and target not in seen:
            seen.add(target)
            urls.append(target)

    # 2. URL, напечатанные обычным текстом
    url_pattern = re.compile(r"https?://\S+")
    for para in doc.paragraphs:
        for match in url_pattern.findall(para.text):
            cleaned = match.rstrip(').,;:»"\'')
            if cleaned not in seen:
                seen.add(cleaned)
                urls.append(cleaned)

    return urls


def resolve_batch_urls(path: str) -> list:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        return extract_urls_from_txt(path)
    elif ext == ".docx":
        return extract_urls_from_docx(path)
    print(f"Неподдерживаемый формат файла: {ext} (нужен .txt или .docx)")
    sys.exit(1)


def resolve_input():
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().strip('"').strip("'")
    else:
        arg = input(
            "Ссылка на видео Facebook ИЛИ путь к .txt/.docx со списком ссылок: "
        ).strip().strip('"').strip("'")

    if not arg:
        print("Ничего не указано.")
        sys.exit(1)

    if os.path.isfile(arg) and os.path.splitext(arg)[1].lower() in (".txt", ".docx"):
        return "batch", resolve_batch_urls(arg)
    return "single", [arg]


def alternate_urls(url: str) -> list:
    """Альтернативные варианты той же ссылки на случай, если основной формат
    упирается в текущий баг экстрактора (см. пояснение в начале файла)."""
    m = re.search(r"facebook\.com/reel/(\d+)", url)
    if not m:
        return []
    video_id = m.group(1)
    return [
        f"https://www.facebook.com/watch/?v={video_id}",
        f"https://mbasic.facebook.com/watch/?v={video_id}",
    ]


def download_one(ydl: YoutubeDL, url: str):
    for attempt, u in enumerate([url] + alternate_urls(url)):
        try:
            if attempt > 0:
                print(f"    Основной формат не сработал, пробую альтернативу: {u}")
            ydl.download([u])
            return True, None
        except Exception as e:
            last_err = str(e)
    return False, last_err


if __name__ == "__main__":
    kind, urls = resolve_input()
    urls = [u for u in urls if u]

    if not urls:
        print("Список ссылок пуст.")
        sys.exit(1)

    print(f"Режим:              {MODE}")
    print(f"Результаты:         {OUTPUT_DIR}")
    print(f"Ссылок к обработке: {len(urls)}\n")

    ok, failed = [], []
    with YoutubeDL(build_options()) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            success, err = download_one(ydl, url)
            if success:
                ok.append(url)
            else:
                failed.append((url, err))
                print(f"    Ошибка: {err}")
            if kind == "batch" and i < len(urls) and DELAY_BETWEEN_DOWNLOADS_SEC:
                time.sleep(DELAY_BETWEEN_DOWNLOADS_SEC)

    if kind == "batch":
        print(f"\nГотово: {len(ok)} успешно, {len(failed)} с ошибками.")
        if failed:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            details_path = os.path.join(OUTPUT_DIR, "failed_links_details.txt")
            retry_path = os.path.join(OUTPUT_DIR, "failed_links_retry.txt")
            with open(details_path, "w", encoding="utf-8") as f:
                for url, err in failed:
                    f.write(f"{url}\t{err}\n")
            with open(retry_path, "w", encoding="utf-8") as f:
                for url, _ in failed:
                    f.write(f"{url}\n")
            print(f"Подробности по ошибкам:            {details_path}")
            print(f"Список для повторного запуска:      {retry_path}")
