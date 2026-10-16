"""
Снижение размера видео: пережатие в выбранное разрешение (через ffmpeg).

Как запустить:
  python compress_video.py "C:\\путь\\к\\видео.mp4"
  python compress_video.py "C:\\путь\\к\\папке"            (все видео в папке, без вложенных)
  python compress_video.py "C:\\путь\\к\\список.txt"       (или .docx — пути к видеофайлам)
  python compress_video.py "..." --quality 720             (max / 1080 / 720 / 480)
  — либо без аргумента, тогда скрипт спросит путь, а затем разрешение.

Нужен ffmpeg (вместе с ffprobe), доступный из PATH, либо укажите путь в FFMPEG_PATH ниже.
Сборка для Windows: https://www.gyan.dev/ffmpeg/builds/
Для списка в формате .docx нужна библиотека:  pip install python-docx

Что делает:
  - Уменьшает кадр так, чтобы его МЕНЬШАЯ сторона не превышала выбранную: 720p — это 1280x720 для
    обычного видео и 720x1280 для вертикального (то же правило, что в video_to_ru_subtitles.py).
    Пропорции сохраняются. Увеличивать картинку скрипт никогда не будет.
  - Перекодирует в H.264 (качество задаётся CRF) и звук в AAC. Видео сжимается и за счёт самого
    кодирования, поэтому вариант "исходный размер" тоже может уменьшить файл (на тяжёлых исходниках).
  - Результаты кладутся в папку compressed/ рядом со скриптом. Исходные файлы не меняются.
  - Если видео уже не больше выбранного размера, оно пропускается (его пережатие почти ничего не
    даст) — это настраивается в RECOMPRESS_IF_SMALLER.
  - Если после сжатия файл не стал меньше исходного, результат удаляется (KEEP_IF_LARGER).

Что теряется: от видео остаётся первая видеодорожка и первая звуковая; дополнительные звуковые
дорожки, встроенные субтитры и главы в результат не попадают. Метаданные (название, дата) копируются.
"""

import json
import os
import re
import subprocess
import sys
import time

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "compressed")   # всегда рядом со скриптом

# До какого размера сжимать: "max" (исходный размер, только пережать), "1080" (Full HD), "720", "480"
# или "ask" — спрашивать при каждом запуске. Ключ --quality перекрывает это значение.
QUALITY = "ask"

CRF = 23                 # качество H.264: меньше = лучше и тяжелее (обычно 18-28; 23 — разумный баланс)
X264_PRESET = "fast"     # ultrafast ... medium ... slow: медленнее = компактнее при том же качестве
AAC_BITRATE = "128k"

FFMPEG_PATH = "ffmpeg"   # если не в PATH: r"C:\\tools\\ffmpeg\\bin\\ffmpeg.exe"

RECOMPRESS_IF_SMALLER = False   # True — пережимать и те видео, что уже не больше выбранного размера
KEEP_IF_LARGER = False          # True — оставлять результат, даже если он получился больше исходного

VALID_EXTENSIONS = {".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg"}

# =============================================================================

QUALITY_VALUES = {"max": 0, "макс": 0, "1080": 1080, "fullhd": 1080, "fhd": 1080,
                  "720": 720, "hd": 720, "480": 480}


# ----------------------------------------------------------------- утилиты

def fmt_size(num_bytes: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if num_bytes < 1024 or unit == "ГБ":
            return f"{num_bytes:.0f} {unit}" if unit == "Б" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}ч {m:02d}м {s:02d}с" if h else f"{m}м {s:02d}с"


def ffprobe_path() -> str:
    if os.path.basename(FFMPEG_PATH).lower().startswith("ffmpeg") and os.path.dirname(FFMPEG_PATH):
        d, name = os.path.split(FFMPEG_PATH)
        return os.path.join(d, name.lower().replace("ffmpeg", "ffprobe", 1))
    return "ffprobe"


def check_tools() -> bool:
    for tool in (FFMPEG_PATH, ffprobe_path()):
        try:
            subprocess.run([tool, "-version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"Ошибка: не найден {tool}. Установите ffmpeg (ffprobe идёт вместе с ним): "
                  "https://www.gyan.dev/ffmpeg/builds/ и добавьте папку bin в PATH "
                  "либо укажите путь в FFMPEG_PATH.")
            return False
    return True


def probe(path: str):
    """(ширина, высота, длительность) или None, если файл не читается как видео."""
    try:
        r = subprocess.run(
            [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        data = json.loads(r.stdout)
        stream = data["streams"][0]
        duration = float(data.get("format", {}).get("duration") or 0)
        return int(stream["width"]), int(stream["height"]), duration
    except (OSError, ValueError, KeyError, IndexError):
        return None


def run_ffmpeg(args: list, duration: float = None) -> tuple:
    """Запускает ffmpeg с индикатором прогресса. Возвращает (успех, текст_ошибки)."""
    cmd = [FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    errors = []
    for line in proc.stdout:
        line = line.strip()
        m = re.match(r"out_time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
        if m:
            if duration:
                done = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                print(f"\r      обработано: {min(100, done / duration * 100):5.1f}%", end="", flush=True)
        elif line and not re.match(r"^[a-z_0-9]+=", line):
            errors.append(line)
    proc.wait()
    if duration:
        print()
    return proc.returncode == 0, "\n".join(errors[-15:])


def unique_path(path: str) -> str:
    """Не затирает существующие файлы: добавляет (2), (3)... к имени."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


# ------------------------------------------------------------- ввод и меню

def ask_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print("\nНет интерактивного ввода, меню показать нельзя. Запустите скрипт в терминале "
              "(в VS Code: окно Terminal, а не панель Output) либо задайте значения заранее: "
              "путь аргументом и --quality.")
        sys.exit(1)


def pop_cli_option(name: str):
    """Вынимает "--name значение" или "--name=значение" из аргументов."""
    args, rest, value, i = sys.argv[1:], [], None, 0
    while i < len(args):
        a = args[i]
        if a == name:
            if i + 1 >= len(args):
                print(f"После {name} нужно указать значение.")
                sys.exit(1)
            value, i = args[i + 1].strip(), i + 2
        elif a.startswith(name + "="):
            value, i = a.split("=", 1)[1].strip(), i + 1
        else:
            rest.append(a)
            i += 1
    sys.argv = [sys.argv[0]] + rest
    return value


def resolve_limit(cli_quality):
    """Возвращает предел меньшей стороны кадра в пикселях (0 = исходный размер)."""
    quality = (cli_quality or QUALITY).strip().lower()
    if quality == "ask":
        print("\nДо какого размера сжать видео?")
        print("  1 — исходный размер (только пережать; выигрыш бывает лишь на тяжёлых исходниках)")
        print("  2 — Full HD, 1080p")
        print("  3 — 720p")
        print("  4 — 480p (самый маленький файл)")
        while True:
            choice = ask_input("Выберите 1-4 [3]: ").strip().lower()
            picked = {"": "720", "1": "max", "2": "1080", "3": "720", "4": "480"}.get(choice)
            if picked is None and choice in QUALITY_VALUES:
                picked = choice
            if picked:
                quality = picked
                break
            print("Введите число от 1 до 4.")
    key = quality.replace("p", "")
    if key not in QUALITY_VALUES:
        print(f'Неизвестное значение "{quality}". Допустимо: max, 1080, 720, 480, ask.')
        sys.exit(1)
    return QUALITY_VALUES[key]


def read_list_file(path: str) -> list:
    """Пути к видеофайлам из .txt (по одной строке; # и пустые строки пропускаются) или .docx."""
    if path.lower().endswith(".docx"):
        try:
            from docx import Document
        except ImportError:
            print("Для чтения .docx нужна библиотека:  pip install python-docx")
            sys.exit(1)
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                lines += [cell.text for cell in row.cells]
    else:
        for enc in ("utf-8-sig", "cp1251"):
            try:
                with open(path, encoding=enc) as f:
                    lines = f.read().splitlines()
                break
            except UnicodeDecodeError:
                continue
        else:
            lines = []
    files, skipped, seen = [], 0, set()
    for raw in lines:
        line = raw.strip().strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        if os.path.isfile(line):
            full = os.path.abspath(line)
            if full not in seen:
                seen.add(full)
                files.append(full)
        else:
            skipped += 1
    if skipped:
        print(f"      Пропущено строк (нет такого файла): {skipped}")
    return files


def resolve_input() -> list:
    raw = sys.argv[1] if len(sys.argv) > 1 else ask_input("Путь к видео, папке ИЛИ списку (.txt / .docx): ")
    raw = os.path.abspath(raw.strip().strip('"').strip("'"))
    if os.path.isdir(raw):
        if os.path.abspath(raw) == os.path.abspath(OUTPUT_DIR):
            print(f"Ошибка: это папка результатов ({OUTPUT_DIR}). Остановлено, чтобы не пережимать готовое.")
            sys.exit(1)
        files = sorted(os.path.join(raw, f) for f in os.listdir(raw)
                       if os.path.splitext(f)[1].lower() in VALID_EXTENSIONS)
    elif os.path.isfile(raw) and os.path.splitext(raw)[1].lower() in (".txt", ".docx"):
        files = read_list_file(raw)
    elif os.path.isfile(raw):
        files = [raw]
    else:
        print(f"Ошибка: не найдено — {raw}")
        sys.exit(1)
    if not files:
        print("Не найдено видеофайлов для обработки.")
        sys.exit(1)
    return files


# ------------------------------------------------------------------ сжатие

def video_filter(limit: int) -> str:
    """Уменьшает кадр так, чтобы меньшая сторона не превышала limit; не увеличивает; чётные размеры."""
    parts = []
    if limit:
        parts.append(
            f"scale=w='if(gt(min(iw,ih),{limit}),if(gte(iw,ih),-2,{limit}),iw)'"
            f":h='if(gt(min(iw,ih),{limit}),if(gte(iw,ih),{limit},-2),ih)'")
    parts += ["scale=trunc(iw/2)*2:trunc(ih/2)*2", "format=yuv420p"]
    return ",".join(parts)


def compress_one(src: str, limit: int, label: str):
    """Возвращает (статус, детали): "ok" | "skipped" | "larger" | "error"."""
    info = probe(src)
    if not info:
        return "error", "не читается как видео (ffprobe)"
    width, height, duration = info

    if limit and min(width, height) <= limit and not RECOMPRESS_IF_SMALLER:
        return "skipped", f"уже {min(width, height)}p — не больше {limit}p"

    stem = os.path.splitext(os.path.basename(src))[0]
    out_path = unique_path(os.path.join(OUTPUT_DIR, f"{stem}_{label}.mp4"))
    args = ["-i", src, "-vf", video_filter(limit),
            "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "0",
            "-c:v", "libx264", "-crf", str(CRF), "-preset", X264_PRESET, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", AAC_BITRATE, "-movflags", "+faststart", out_path]
    try:
        ok, err = run_ffmpeg(args, duration=duration)
    except KeyboardInterrupt:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise
    if not ok:
        if os.path.exists(out_path):
            os.remove(out_path)
        return "error", err.splitlines()[-1] if err else "ffmpeg завершился с ошибкой"

    old_size, new_size = os.path.getsize(src), os.path.getsize(out_path)
    if new_size >= old_size and not KEEP_IF_LARGER:
        os.remove(out_path)
        return "larger", f"{fmt_size(old_size)} -> {fmt_size(new_size)}: файл не стал меньше, результат удалён"
    return "ok", (out_path, old_size, new_size)


def main():
    try:  # Windows-консоль в старой кодировке иначе падает на кириллице в именах файлов
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    cli_quality = pop_cli_option("--quality")
    if not check_tools():
        sys.exit(1)
    files = resolve_input()
    limit = resolve_limit(cli_quality)
    label = f"{limit}p" if limit else "orig"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"\nФайлов: {len(files)} | размер: {'исходный' if not limit else f'до {limit}p'} | "
          f"CRF {CRF}, пресет {X264_PRESET}")
    print(f"Результаты: {OUTPUT_DIR}\n")

    t_all, saved, stats, problems = time.time(), 0, {"ok": 0, "skipped": 0, "larger": 0, "error": 0}, []
    for i, src in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {os.path.basename(src)}")
        status, details = compress_one(src, limit, label)
        stats[status] += 1
        if status == "ok":
            out_path, old_size, new_size = details
            saved += old_size - new_size
            print(f"      готово: {fmt_size(old_size)} -> {fmt_size(new_size)} "
                  f"(-{(1 - new_size / old_size) * 100:.0f}%)  {os.path.basename(out_path)}")
        else:
            print(f"      {'ПРОПУЩЕНО' if status == 'skipped' else 'БЕЗ РЕЗУЛЬТАТА' if status == 'larger' else 'ОШИБКА'}: {details}")
            if status == "error":
                problems.append((os.path.basename(src), details))

    print("\n" + "=" * 62)
    print(f"  Сжато: {stats['ok']} | пропущено: {stats['skipped']} | не стало меньше: {stats['larger']} "
          f"| ошибок: {stats['error']}")
    print(f"  Освобождено: {fmt_size(saved)} за {fmt_duration(time.time() - t_all)}")
    for name, err in problems:
        print(f"    - {name}: {err}")
    print("=" * 62)
    if stats["error"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nОстановлено пользователем (недоделанный файл удалён).")
        sys.exit(1)
