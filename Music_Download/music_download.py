import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


APP_NAME = "Music Downloader"
APP_VERSION = "1.0"

SUPPORTED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "soundcloud.com",
    "on.soundcloud.com",
    "bandcamp.com",
)

YOUTUBE_HOSTS = (
    "youtube.com",
    "youtu.be",
)


def is_supported_host(hostname):
    hostname = (hostname or "").lower()

    return any(
        hostname == host
        or hostname.endswith("." + host)
        for host in SUPPORTED_HOSTS
    )


def is_youtube_url(url):
    hostname = (
        urllib.parse.urlparse(url).hostname
        or ""
    ).lower()

    return any(
        hostname == host
        or hostname.endswith("." + host)
        for host in YOUTUBE_HOSTS
    )


def validate_url(url):
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            "Нужна обычная ссылка http:// или https://"
        )

    if not is_supported_host(parsed.hostname):
        raise ValueError(
            "Эта версия поддерживает только "
            "YouTube / YouTube Music, SoundCloud и Bandcamp."
        )


def ensure_yt_dlp():
    if importlib.util.find_spec("yt_dlp") is None:
        print()
        print("Не найден yt-dlp.")
        print()
        print("Установи его командой:")
        print('  py -m pip install -U "yt-dlp[default]"')
        print()
        sys.exit(2)


def ensure_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg or not ffprobe:
        print()
        print("Не найдены ffmpeg и/или ffprobe.")
        print()
        print(
            "Они нужны для извлечения аудио, "
            "метаданных и обложек."
        )
        print()
        print(
            "Установи FFmpeg и убедись, "
            "что ffmpeg и ffprobe доступны через PATH."
        )
        print()
        sys.exit(2)


def youtube_js_args(url):
    """
    Modern YouTube extraction needs an external JS runtime.
    Deno is yt-dlp's recommended/default runtime.
    Node and QuickJS are supported too, but must be enabled explicitly.
    """
    if not is_youtube_url(url):
        return []

    if shutil.which("deno"):
        return []

    if shutil.which("node"):
        return [
            "--js-runtimes",
            "node",
        ]

    if shutil.which("qjs"):
        return [
            "--js-runtimes",
            "quickjs",
        ]

    print()
    print("Для YouTube не найден JavaScript runtime.")
    print()
    print(
        "Для стабильной работы YouTube "
        "сейчас рекомендуется Deno."
    )
    print()
    print("Windows:")
    print("  winget install DenoLand.Deno")
    print()
    print(
        "После установки закрой и заново открой CMD, "
        "затем проверь:"
    )
    print("  deno --version")
    print()
    sys.exit(2)


def run_command(command, capture=False):
    kwargs = {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }

    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    return subprocess.run(
        command,
        **kwargs,
    )


def base_yt_dlp_command(js_args):
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--windows-filenames",
        *js_args,
    ]


def inspect_url(url, js_args):
    """
    Ask yt-dlp what the URL represents without downloading media.
    We only need enough metadata to decide whether this is a
    single track or a collection (playlist/album/set).
    """
    command = base_yt_dlp_command(js_args) + [
        "--flat-playlist",
        "--dump-single-json",
        "--quiet",
        "--no-warnings",
        url,
    ]

    result = run_command(
        command,
        capture=True,
    )

    if result.returncode != 0:
        message = (
            result.stderr.strip()
            or "yt-dlp не смог прочитать ссылку."
        )

        raise RuntimeError(message)

    raw = result.stdout.strip()

    if not raw:
        raise RuntimeError(
            "yt-dlp не вернул информацию о ссылке."
        )

    # --dump-single-json normally produces one JSON object.
    # If an extractor writes extra lines, try the last JSON-looking line.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            line = line.strip()

            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass

    raise RuntimeError(
        "Не удалось разобрать ответ yt-dlp."
    )


def clean_folder_name(name):
    forbidden = '<>:"/\\|?*'

    cleaned = "".join(
        "_" if char in forbidden else char
        for char in str(name)
    )

    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" .")

    return cleaned[:160] or "Playlist"


def detect_collection(info):
    if info.get("_type") == "playlist":
        return True

    entries = info.get("entries")

    if isinstance(entries, list):
        return True

    return False


def collection_title(info):
    return (
        info.get("title")
        or info.get("playlist_title")
        or info.get("album")
        or info.get("id")
        or "Playlist"
    )


def count_entries(info):
    entries = info.get("entries")

    if isinstance(entries, list):
        return len(entries)

    count = info.get("playlist_count")

    if isinstance(count, int):
        return count

    return None


def make_output_template(
    output_root,
    is_collection,
    title=None,
):
    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        "%(artist,creator,uploader|Unknown Artist)s"
        " - "
        "%(track,title)s.%(ext)s"
    )

    if not is_collection:
        return str(
            output_root / filename
        )

    folder = output_root / clean_folder_name(
        title or "Playlist"
    )

    folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        "%(playlist_index)03d"
        " - "
        "%(artist,creator,uploader|Unknown Artist)s"
        " - "
        "%(track,title)s.%(ext)s"
    )

    return str(
        folder / filename
    )


def make_archive_path(
    output_root,
    is_collection,
    title=None,
):
    if is_collection:
        folder = output_root / clean_folder_name(
            title or "Playlist"
        )

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        return folder / "download_archive.txt"

    return output_root / "download_archive.txt"


def build_download_command(
    url,
    js_args,
    output_template,
    mp3=False,
    limit=None,
    archive_path=None,
):
    command = base_yt_dlp_command(
        js_args
    )

    command += [
        "--continue",
        "--no-overwrites",
        "--embed-metadata",
        "--embed-thumbnail",
        "--format",
        "bestaudio/best",
        "--extract-audio",
    ]

    if mp3:
        command += [
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
        ]
    else:
        command += [
            "--audio-format",
            "best",
        ]

    if limit is not None:
        command += [
            "--playlist-end",
            str(limit),
        ]

    if archive_path is not None:
        command += [
            "--download-archive",
            str(archive_path),
        ]

    command += [
        "--output",
        output_template,
        url,
    ]

    return command


def print_summary(
    url,
    info,
    is_collection,
    output_root,
    mp3,
    limit,
    archive,
):
    print()
    print("=" * 64)
    print(f"{APP_NAME} {APP_VERSION}")
    print("=" * 64)

    extractor = (
        info.get("extractor_key")
        or info.get("extractor")
        or "unknown"
    )

    print(f"Источник: {extractor}")

    if is_collection:
        title = collection_title(info)
        count = count_entries(info)

        print("Режим:    плейлист / альбом")
        print(f"Название: {title}")

        if count is not None:
            print(f"Найдено:  {count}")

        if limit is not None:
            print(
                f"Лимит:     первые {limit}"
            )

        folder = output_root / clean_folder_name(
            title
        )

        print(f"Папка:    {folder.resolve()}")
    else:
        title = (
            info.get("track")
            or info.get("title")
            or "Без названия"
        )

        artist = (
            info.get("artist")
            or info.get("creator")
            or info.get("uploader")
            or "Unknown Artist"
        )

        print("Режим:    один трек")
        print(f"Исполнитель: {artist}")
        print(f"Трек:        {title}")
        print(
            f"Папка:       {output_root.resolve()}"
        )

        if limit is not None:
            print(
                "Примечание: --limit для одиночного "
                "трека ни на что не влияет."
            )

    if mp3:
        print("Формат:   MP3, конвертация включена")
    else:
        print(
            "Формат:   лучший исходный аудиоформат"
        )

    if archive:
        print(
            "Архив:    включен — повторно скачанные "
            "ID будут пропускаться"
        )

    print("=" * 64)
    print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Скачать аудио по ссылке на трек, "
            "плейлист или альбом. "
            "Поддерживаются YouTube / YouTube Music, "
            "SoundCloud и Bandcamp."
        )
    )

    parser.add_argument(
        "url",
        help=(
            "Ссылка на трек, плейлист или альбом"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        default="Music",
        help=(
            "Корневая папка для музыки "
            "(по умолчанию: Music)"
        ),
    )

    parser.add_argument(
        "--mp3",
        action="store_true",
        help=(
            "Конвертировать результат в MP3. "
            "Без этой опции сохраняется лучший "
            "исходный аудиоформат."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Для плейлиста/альбома скачать "
            "только первые N элементов."
        ),
    )

    parser.add_argument(
        "--archive",
        action="store_true",
        help=(
            "Вести download_archive.txt и "
            "не скачивать уже записанные туда элементы."
        ),
    )

    args = parser.parse_args()

    try:
        validate_url(args.url)

        if (
            args.limit is not None
            and args.limit <= 0
        ):
            raise ValueError(
                "--limit должен быть больше нуля."
            )

        ensure_yt_dlp()
        ensure_ffmpeg()

        js_args = youtube_js_args(
            args.url
        )

        print("Читаю ссылку...")

        info = inspect_url(
            args.url,
            js_args,
        )

        is_collection = detect_collection(
            info
        )

        title = (
            collection_title(info)
            if is_collection
            else None
        )

        output_root = Path(
            args.output
        )

        output_template = make_output_template(
            output_root,
            is_collection,
            title,
        )

        archive_path = None

        if args.archive:
            archive_path = make_archive_path(
                output_root,
                is_collection,
                title,
            )

        print_summary(
            args.url,
            info,
            is_collection,
            output_root,
            args.mp3,
            args.limit,
            args.archive,
        )

        command = build_download_command(
            args.url,
            js_args,
            output_template,
            mp3=args.mp3,
            limit=args.limit,
            archive_path=archive_path,
        )

        result = run_command(command)

        print()

        if result.returncode == 0:
            print("=" * 64)
            print("Готово.")
            print("=" * 64)
        else:
            print("=" * 64)
            print(
                "yt-dlp завершился с ошибкой."
            )
            print(
                "Проверь сообщения выше — "
                "там обычно указана причина."
            )
            print("=" * 64)

            sys.exit(
                result.returncode
            )

    except KeyboardInterrupt:
        print()
        print()
        print("Остановлено пользователем.")
        print(
            "Уже полностью скачанные файлы "
            "останутся на месте."
        )
        sys.exit(130)

    except Exception as error:
        print()
        print(f"Ошибка: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
