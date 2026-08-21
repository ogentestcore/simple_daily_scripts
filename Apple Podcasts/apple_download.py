import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET


USER_AGENT = "Mozilla/5.0 ApplePodcastDownloader/2.1"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def request(url):
    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT}
        )
    )


def get_json(url):
    with request(url) as response:
        return json.load(response)


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    return name[:160] or "podcast"


def parse_apple_url(url):
    parsed = urllib.parse.urlparse(url)

    match = re.search(r"/id(\d+)", parsed.path)

    if not match:
        raise ValueError("Не нашел ID подкаста в ссылке.")

    show_id = match.group(1)

    query = urllib.parse.parse_qs(parsed.query)
    episode_id = query.get("i", [None])[0]

    return show_id, episode_id


def get_show_info(show_id):
    data = get_json(
        f"https://itunes.apple.com/lookup?id={show_id}"
    )

    for item in data.get("results", []):
        feed_url = item.get("feedUrl")

        if feed_url:
            return {
                "title": (
                    item.get("collectionName")
                    or item.get("trackName")
                    or f"podcast_{show_id}"
                ),
                "feed_url": feed_url,
            }

    raise RuntimeError(
        "Apple API не вернул RSS подкаста."
    )



def normalize_episode_type(value):
    """
    Apple Podcasts recognizes three episode types:
    full, bonus, trailer.

    If the RSS feed does not specify a type, treat it as a regular episode.
    """
    if not value:
        return "full"

    value = value.strip().lower()

    if value in {"full", "bonus", "trailer"}:
        return value

    return "full"


def get_feed_episodes(feed_url):
    print("Читаю RSS...")

    with request(feed_url) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)

    channel = root.find("channel")

    if channel is None:
        raise RuntimeError(
            "RSS имеет неизвестный формат."
        )

    podcast_title = channel.findtext("title") or "Podcast"

    episodes = []

    for item in channel.findall("item"):
        title = item.findtext("title") or "Без названия"

        enclosure = item.find("enclosure")

        if enclosure is None:
            continue

        audio_url = enclosure.attrib.get("url")

        if not audio_url:
            continue

        episode_type = normalize_episode_type(
            item.findtext(
                f"{{{ITUNES_NS}}}episodeType"
            )
        )

        episode_number = item.findtext(
            f"{{{ITUNES_NS}}}episode"
        )

        season_number = item.findtext(
            f"{{{ITUNES_NS}}}season"
        )

        episodes.append({
            "title": title,
            "audio_url": audio_url,
            "guid": item.findtext("guid"),
            "date": item.findtext("pubDate"),
            "episode_type": episode_type,
            "episode_number": episode_number,
            "season_number": season_number,
        })

    return podcast_title, episodes


def choose_extension(audio_url, content_type=""):
    path = urllib.parse.urlparse(audio_url).path
    suffix = Path(path).suffix.lower()

    if suffix in {".mp3", ".m4a", ".mp4", ".wav", ".aac"}:
        return suffix

    content_type = content_type.lower()

    if "mp4" in content_type or "m4a" in content_type:
        return ".m4a"

    if "aac" in content_type:
        return ".aac"

    return ".mp3"


def download_file(
    audio_url,
    title,
    output_dir,
    prefix=None
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    safe_title = clean_filename(title)

    if prefix:
        base_name = f"{prefix} - {safe_title}"
    else:
        base_name = safe_title

    # Сначала открываем URL, чтобы определить тип файла.
    with request(audio_url) as response:
        content_type = response.headers.get(
            "Content-Type",
            ""
        )

        extension = choose_extension(
            audio_url,
            content_type
        )

        filename = output_dir / (
            base_name + extension
        )

        partial = output_dir / (
            base_name + extension + ".part"
        )

        # Уже скачивали — пропускаем.
        if filename.exists():
            print("уже есть — пропуск")
            return filename, True

        total = response.headers.get(
            "Content-Length"
        )

        total = int(total) if total else None

        downloaded = 0

        with open(partial, "wb") as file:
            while True:
                chunk = response.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                file.write(chunk)

                downloaded += len(chunk)

                if total:
                    percent = (
                        downloaded / total * 100
                    )

                    print(
                        f"\r    {percent:5.1f}%",
                        end="",
                        flush=True
                    )

                else:
                    mb = (
                        downloaded
                        / 1024
                        / 1024
                    )

                    print(
                        f"\r    {mb:.1f} MB",
                        end="",
                        flush=True
                    )

        partial.replace(filename)

        print()

        return filename, False


def download_whole_podcast(
    show_id,
    output_root,
    limit=None,
    exclude_trailers=False
):
    show = get_show_info(show_id)

    print(
        f"RSS: {show['feed_url']}"
    )

    podcast_title, episodes = (
        get_feed_episodes(
            show["feed_url"]
        )
    )

    if not episodes:
        raise RuntimeError(
            "В RSS не найдено ни одного выпуска."
        )

    total_rss = len(episodes)
    full_count = sum(
        1 for episode in episodes
        if episode["episode_type"] == "full"
    )
    bonus_count = sum(
        1 for episode in episodes
        if episode["episode_type"] == "bonus"
    )
    trailer_count = sum(
        1 for episode in episodes
        if episode["episode_type"] == "trailer"
    )

    print()
    print(f"Подкаст: {podcast_title}")
    print()
    print(f"Всего выпусков в RSS: {total_rss}")
    print(f"  Обычных:             {full_count}")
    print(f"  Бонусов:              {bonus_count}")
    print(f"  Трейлеров:             {trailer_count}")

    if exclude_trailers:
        episodes = [
            episode
            for episode in episodes
            if episode["episode_type"] != "trailer"
        ]

        print()
        print(
            f"Трейлеры исключены. "
            f"Будет доступно для скачивания: {len(episodes)}"
        )
    else:
        print()
        print(
            "Трейлеры включены. "
            "Используй --exclude-trailers, "
            "чтобы их не скачивать."
        )

    if not episodes:
        raise RuntimeError(
            "После фильтрации не осталось выпусков для скачивания."
        )

    # RSS обычно идет от нового к старому.
    # Нам удобнее сохранять от старого к новому.
    #
    # Нумерация архивная: после фильтрации выпуски получают
    # последовательные номера 001, 002, 003...
    # Бонусы сохраняются и участвуют в этой последовательности.
    episodes = list(reversed(episodes))

    indexed_episodes = list(
        enumerate(episodes, start=1)
    )

    # --limit 3 = три самых свежих выпуска,
    # но с их настоящими номерами.
    if limit:
        indexed_episodes = (
            indexed_episodes[-limit:]
        )

        print(
            f"Для теста скачиваем: "
            f"{len(indexed_episodes)}"
        )

    print()

    output_dir = (
        output_root
        / clean_filename(podcast_title)
    )

    errors = []

    total_count = len(episodes)

    for number, episode in indexed_episodes:
        prefix = str(number).zfill(
            len(str(total_count))
        )

        type_label = ""

        if episode["episode_type"] == "bonus":
            type_label = " [BONUS]"
        elif episode["episode_type"] == "trailer":
            type_label = " [TRAILER]"

        print(
            f"[{number}/{total_count}]"
            f"{type_label} "
            f"{episode['title']}"
        )

        try:
            download_file(
                episode["audio_url"],
                episode["title"],
                output_dir,
                prefix=prefix,
            )

        except KeyboardInterrupt:
            print(
                "\n\nОстановлено пользователем."
            )

            print(
                "Уже скачанные файлы "
                "останутся на месте."
            )

            sys.exit(0)

        except Exception as error:
            print(
                f"    ОШИБКА: {error}"
            )

            errors.append(
                (
                    number,
                    episode["title"],
                    str(error),
                )
            )

        print()

    print("=" * 60)
    print("Готово.")
    print(
        f"Папка: "
        f"{output_dir.resolve()}"
    )

    if errors:
        print()
        print(
            f"Не удалось скачать: "
            f"{len(errors)}"
        )

        for number, title, error in errors:
            print(
                f"  {number}. "
                f"{title}: {error}"
            )


def find_single_episode(
    show_id,
    episode_id
):
    url = (
        "https://itunes.apple.com/lookup?"
        f"id={show_id}"
        "&entity=podcastEpisode"
        "&limit=200"
    )

    data = get_json(url)

    for item in data.get(
        "results",
        []
    ):
        if (
            str(item.get("trackId"))
            == str(episode_id)
        ):
            return item

    raise RuntimeError(
        "Apple API не нашел этот выпуск."
    )


def download_single_episode(
    show_id,
    episode_id,
    output_root
):
    episode = find_single_episode(
        show_id,
        episode_id
    )

    title = (
        episode.get("trackName")
        or f"episode_{episode_id}"
    )

    audio_url = episode.get(
        "episodeUrl"
    )

    if not audio_url:
        raise RuntimeError(
            "Apple API не вернул "
            "URL аудиофайла."
        )

    print(f"Выпуск: {title}")

    filename, skipped = download_file(
        audio_url,
        title,
        output_root
    )

    print()
    print(
        f"Готово: {filename.resolve()}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Скачивание Apple Podcasts: "
            "один выпуск или весь подкаст."
        )
    )

    parser.add_argument(
        "url",
        help=(
            "Ссылка Apple Podcasts "
            "на выпуск или на весь подкаст"
        )
    )

    parser.add_argument(
        "-o",
        "--output",
        default="Podcasts",
        help=(
            "Папка для сохранения "
            "(по умолчанию Podcasts)"
        )
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Скачать только N "
            "самых свежих выпусков"
        )
    )

    parser.add_argument(
        "--exclude-trailers",
        action="store_true",
        help=(
            "Не скачивать выпуски типа trailer. "
            "Бонусные выпуски сохраняются."
        )
    )

    args = parser.parse_args()

    try:
        show_id, episode_id = (
            parse_apple_url(args.url)
        )

        output_root = Path(
            args.output
        )

        print(
            f"Podcast ID: {show_id}"
        )

        if episode_id:
            print(
                f"Episode ID: {episode_id}"
            )

            print(
                "Режим: один выпуск"
            )

            download_single_episode(
                show_id,
                episode_id,
                output_root,
            )

        else:
            print(
                "Режим: весь подкаст"
            )

            download_whole_podcast(
                show_id,
                output_root,
                limit=args.limit,
                exclude_trailers=args.exclude_trailers,
            )

    except Exception as error:
        print(
            f"\nОшибка: {error}",
            file=sys.stderr
        )

        sys.exit(1)


if __name__ == "__main__":
    main()