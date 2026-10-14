"""
Видео -> распознавание речи -> локальный перевод -> готовое видео с субтитрами.
ОДИН самодостаточный файл: соседние скрипты (youtube_download.py и т.д.) НЕ нужны.

Что делает (по шагам):
  1. Получает видео: скачивает по ссылке через yt-dlp ИЛИ берёт готовый
     файл с диска (можно передать путь к видео вместо ссылки).
  2. Распознаёт речь (faster-whisper) -> субтитры на языке оригинала.
  3. Переводит субтитры на русский локально: LLM Gemma через Ollama или OPUS-MT
     (на выбор; после первой загрузки моделей интернет не нужен).
  4. Вшивает субтитры в видео (ffmpeg) и кладёт рядом отдельный .srt.

Как запустить:
  python video_to_ru_subtitles.py "https://www.youtube.com/watch?v=..."
  python video_to_ru_subtitles.py "C:\\путь\\к\\видео.mp4"
  — либо без аргумента, тогда скрипт спросит сам.
  Режим субтитров можно выбрать при запуске, не правя файл:
  python video_to_ru_subtitles.py "ссылка" --mode srt       (или soft / burn)
  Движок перевода (TRANSLATOR в CONFIG; по умолчанию "ask" — спросит меню):
  python video_to_ru_subtitles.py "ссылка" --translator opus      (или ollama)
  Для движка ollama модель берётся из OLLAMA_MODEL (по умолчанию translategemma:4b;
  нет в Ollama — скрипт предложит скачать; "ask" — список установленных) либо ключом:
  --model qwen2.5:7b

  СРАВНЕНИЕ ПЕРЕВОДЧИКОВ на ваших данных (быстро, видео не создаётся):
  python video_to_ru_subtitles.py "ссылка_или_файл" --compare
  Переведёт первые 20 реплик каждым движком из COMPARE_ENGINES, покажет
  переводы рядом и скорость (секунд на реплику, оценка на всё видео),
  отчёт сохранит в work/compare_<имя>_<дата-время>.txt (старые не затираются).
  Прогнать только часть движков (быстрее, без ожидания Gemma):
  python video_to_ru_subtitles.py "ссылка_или_файл" --compare --engines opus
  Имена для --engines: opus, gemma (= ollama:translategemma:4b), ollama:<модель>, all.

  Меню показываются только в терминале. В VS Code запускайте из терминала
  внизу (а не из панели Output / Code Runner), иначе ввода нет.

Один раз установить:
  pip install -U "yt-dlp[default]" faster-whisper ollama
  + ffmpeg в PATH (или путь в FFMPEG_PATH ниже) — ОБЯЗАТЕЛЕН, на нём держится
    и склейка дорожек, и вшивание субтитров. Сборка с libass (для режима
    "burn") есть в стандартных сборках https://www.gyan.dev/ffmpeg/builds/
  + для движка opus:  pip install ctranslate2 transformers sentencepiece huggingface_hub
    (ctranslate2 и huggingface_hub обычно уже стоят вместе с faster-whisper).
    Модели скачиваются с Hugging Face при первом запуске и дальше работают офлайн.
  + для движка ollama: Ollama с хотя бы одной скачанной моделью. Запускать её
    вручную НЕ нужно: если сервер не запущен, скрипт поднимет его сам
    (ollama serve) и оставит работать после завершения. Для --compare модель
    translategemma:4b скрипт предложит скачать сам.
  + для YouTube: deno.exe (положите рядом со скриптом, пропишите в DENO_PATH
    или добавьте в PATH) — подробности в youtube_download.py

Три режима субтитров (SUBTITLE_MODE в CONFIG или --mode):
  "srt"  — только файл субтитров .srt кладётся рядом с видео под тем же именем.
           Быстрее всего, видео не трогается; VLC и PotPlayer подхватывают
           такие субтитры сами. Если рядом уже лежат чужие субтитры с этим
           именем, файл получает суффикс .ru.srt, чтобы их не затереть.
  "burn" — текст вшивается в САМУ КАРТИНКУ (hardcode). Работает в любом
           плеере и на любом устройстве, отключить нельзя. Видео при этом
           ПЕРЕКОДИРУЕТСЯ (H.264/AAC) — это дольше всего остального
           и чуть теряет в качестве. Результат: .mp4
  "soft" — субтитры идут отдельной дорожкой внутри файла (включаются и
           выключаются в плеере). Видео НЕ перекодируется — готово за
           секунды. Результат: .mkv (контейнер, который принимает любые
           кодеки; встроенные субтитры в .mp4 поддерживаются плеерами хуже).

Устойчивость к сбоям: самые долгие шаги (распознавание и перевод) результат
сохраняют в папку work/. Если скрипт упал на полпути (например, не был
запущен Ollama) — просто запустите ещё раз: готовые шаги будут пропущены.
Перевод кэшируется отдельно для каждого движка и модели: выбрали другой —
он переведёт заново, а распознавание речи пересчитываться не будет.
Внимание: если прервать скрипт ВО ВРЕМЯ перевода, перевод начнётся сначала
(сохраняется только законченный результат шага).
Чтобы пересчитать с нуля (другая модель Whisper) — удалите папку work.

Качество — это важно знать заранее:
  - Whisper на шумной записи или редком языке может ошибаться или
    "додумывать" фразы в тишине; чем крупнее модель, тем реже.
  - Качество перевода зависит от движка и пары языков; на японском и при
    идиомах проверяйте выборочно. Нейропереводчик OPUS-MT переводит реплики
    по отдельности, без контекста; LLM через Ollama контекст учитывает, но
    на CPU намного медленнее. Для выбора запустите --compare на своём видео.
  - Whisper режет речь на реплики посреди предложений; перед переводом скрипт
    склеивает такие обрывки в целые предложения (MERGE_SENTENCES) и делит перевод
    обратно по таймингам пропорционально длине. Деление приблизительное: граница
    между двумя репликами может сместиться на слово-два.
  - OPUS-MT распространяется под Apache-2.0, Gemma — по условиям Google на Gemma.
  - Модели OPUS для скачивания — сторонние конвертации в формат CTranslate2
    (см. OPUS_REPO_TEMPLATE); при желании подставьте свои.
  - Если перевод массово не удался (например, Ollama не отвечает), скрипт
    остановится, а не вошьёт в видео непереведённый текст.

Ответственное использование: скачивайте и обрабатывайте только то, на что у
вас есть права или явное разрешение правообладателя.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# Безвредные предупреждения Hugging Face/transformers (до импорта самих библиотек)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "downloads")   # скачанные исходники
WORK_DIR = os.path.join(SCRIPT_DIR, "work")            # промежуточные .srt (кэш)
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "subtitled")     # ГОТОВЫЙ результат

# --- Скачивание ---
MAX_HEIGHT = 1080          # не качать выше этого разрешения (0 = без ограничения).
                           # Для "burn" видео всё равно перекодируется, а 4K
                           # перекодируется очень долго.
DENO_PATH = ""             # путь к deno.exe, если нет в PATH (см. youtube_download.py)
COOKIES_FROM_BROWSER = ""  # "chrome" / "firefox" / "edge" — для сайтов с логином
COOKIES_FILE = ""          # либо путь к cookies.txt (Netscape)
TRIM_FILENAME_LENGTH = 100 # обрезка длинных названий (иначе падает запись файла)

# --- Распознавание речи ---
# tiny / base / small / medium / large-v3. large-v3 — лучшее качество (особенно для японского,
# китайского и шумных записей), но на CPU примерно вдвое медленнее medium (оценка) и весит
# около 3 ГБ. Не хватает времени или памяти — поставьте "medium" или "small".
WHISPER_MODEL_SIZE = "large-v3"
DEVICE = "cpu"                  # "cpu" или "cuda" (видеокарта NVIDIA)
COMPUTE_TYPE = "int8"           # "int8" для cpu, "float16" для cuda
LANGUAGE = None                 # None = определится само, либо "ja", "es", "en"...

# --- Движок перевода ---
# "ollama" — Gemma (или другая LLM) через Ollama, настройки ниже: лучшее качество, на CPU медленно.
# "opus"   — OPUS-MT (Helsinki-NLP, Apache-2.0): очень быстро; своя малая модель на каждую пару
#            языков; если прямой пары нет — перевод через английский (для японского ненадёжен).
# "ask"    — спрашивать при каждом запуске. Ключ --translator перекрывает значение.
# (Движок NLLB убран — см. заметку в блоке движков ниже.)
TRANSLATOR = "ask"

# Модели для opus скачиваются с Hugging Face при первом запуске (нужен интернет).
# Это СТОРОННИЕ конвертации в формат CTranslate2 — при желании подставьте свои.
OPUS_REPO_TEMPLATE = "gaudi/opus-mt-{pair}-ctranslate2"
NMT_BATCH_SIZE = 16     # реплик за один проход нейропереводчика
NMT_BEAM_SIZE = 2       # шире луч = чуть лучше и медленнее (1 — самый быстрый)
NMT_SPLIT_SENTENCES = True   # переводить реплику по предложениям (меньше потерь текста)

# Whisper режет речь на реплики посреди предложений ("She does" / "look pretty good").
# Переводчик, получив обрывок, ошибается. Склеиваем соседние реплики в целые предложения,
# переводим их целиком и делим перевод обратно по таймингам (пропорционально длине).
MERGE_SENTENCES = True
MERGE_MAX_SEGMENTS = 4   # не склеивать больше стольких реплик подряд
MERGE_MAX_GAP = 1.5      # пауза (секунды), после которой реплики НЕ склеиваются
# У этих языков Whisper отдаёт короткие реплики-фразы без знака в конце, и склейка путает
# разных говорящих (на тесте с китайским перевод "уезжал" на соседние реплики). Для них
# переводится каждая реплика отдельно.
MERGE_SKIP_LANGS = ("zh", "ja", "ko")
CT2_THREADS = 0         # 0 = по умолчанию; можно указать число физических ядер CPU

# --- Режим сравнения (python ... --compare) ---
# Движки для теста: "opus", "ollama:<модель>" (можно несколько ollama-моделей).
COMPARE_ENGINES = ["opus", "ollama:translategemma:4b"]
COMPARE_LINES = 20       # сколько первых реплик переводить в тесте
COMPARE_SECONDS = 180    # если распознавания в кэше нет — распознать только первые N секунд

# --- Перевод через Ollama ---
# Модель для перевода. Имя модели (как в "ollama list") ИЛИ "ask" — показать список
# установленных моделей и спросить при каждом запуске. По умолчанию TranslateGemma 4B:
# на тестах (японский, китайский, немецкий, испанский) она давала лучший перевод.
# Ключ --model перекрывает это значение. Если модели нет в Ollama, скрипт предложит
# её скачать, а при отказе — выбрать из установленных.
OLLAMA_MODEL = "translategemma:4b"
OLLAMA_PATH = ""            # путь к ollama(.exe), если его нет в PATH
OLLAMA_START_TIMEOUT = 30   # сколько секунд ждать запуска сервера Ollama
TARGET_LANGUAGE = "русский"
BATCH_SIZE = 20          # реплик за один запрос к модели
CONTEXT_LINES = 2        # сколько предыдущих реплик показывать как контекст
TEMPERATURE = 0.2

# --- Субтитры в видео ---
# "srt"  — только файл субтитров рядом с видео (быстрее всего; VLC/PotPlayer подхватят сами)
# "soft" — субтитры отдельной дорожкой внутри .mkv (быстро; включаются в плеере)
# "burn" — вшить в картинку, .mp4 (работает везде, но видео перекодируется — долго)
# "ask"  — спрашивать при каждом запуске. Ключ --mode перекрывает это значение.
SUBTITLE_MODE = "ask"

# Оформление для режима "burn". Размеры заданы в условных единицах libass
# (кадр = 288 по высоте): FONT_SIZE 16 ~ 5.5% высоты кадра. Не нравится
# размер — меняйте FONT_SIZE (мельче: 12-14, крупнее: 18-20).
FONT_NAME = "Arial"     # шрифт должен быть в системе и уметь кириллицу
FONT_SIZE = 16
OUTLINE = 1.5           # толщина чёрной обводки
MARGIN_V = 15           # отступ от нижнего края

CRF = 20                # качество H.264: меньше = лучше и тяжелее (обычно 18-23)
X264_PRESET = "fast"    # ultrafast ... medium ... slow: быстрее = больше файл
AAC_BITRATE = "192k"

FFMPEG_PATH = "ffmpeg"  # если не в PATH: r"C:\\tools\\ffmpeg\\bin\\ffmpeg.exe"

REUSE_INTERMEDIATE = True   # пропускать шаги, результат которых уже лежит в work/

# =============================================================================

LANG_CODES = {  # русское название языка -> код Whisper/ISO (для пропуска и для движков)
    "русский": "ru", "английский": "en", "испанский": "es",
    "французский": "fr", "немецкий": "de", "японский": "ja",
    "корейский": "ko", "китайский": "zh", "итальянский": "it",
    "португальский": "pt", "украинский": "uk",
}
LANG_NAMES_EN = {  # код -> английское название (для формата запроса TranslateGemma)
    "ru": "Russian", "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "it": "Italian", "pt": "Portuguese",
    "uk": "Ukrainian", "pl": "Polish", "tr": "Turkish", "ar": "Arabic", "nl": "Dutch",
}
LANG_ISO3 = {   # для метки языка дорожки субтитров в режиме "soft"
    "русский": "rus", "английский": "eng", "испанский": "spa",
    "французский": "fra", "немецкий": "deu", "японский": "jpn",
}


# ----------------------------------------------------------------- утилиты

def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}ч {m:02d}м {s:02d}с" if h else f"{m}м {s:02d}с"


def format_timestamp(seconds: float) -> str:
    """Секунды -> формат SRT: ЧЧ:ММ:СС,ммм"""
    ms_total = round(seconds * 1000)
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def read_srt(path: str) -> list:
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()
    entries = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        entries.append({"timecode": lines[1].strip(), "text": "\n".join(lines[2:]).strip()})
    return entries


def write_srt(entries: list, path: str, key: str = "text"):
    with open(path, "w", encoding="utf-8") as f:
        for i, e in enumerate(entries, start=1):
            f.write(f"{i}\n{e['timecode']}\n{e[key]}\n\n")


def ffprobe_path() -> str:
    if os.path.basename(FFMPEG_PATH).lower().startswith("ffmpeg") and os.path.dirname(FFMPEG_PATH):
        d, name = os.path.split(FFMPEG_PATH)
        return os.path.join(d, name.lower().replace("ffmpeg", "ffprobe", 1))
    return "ffprobe"


def get_duration(path: str):
    """Длительность файла в секундах или None, если ffprobe недоступен."""
    try:
        r = subprocess.run(
            [ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return float(r.stdout.strip())
    except (OSError, ValueError):
        return None


def run_ffmpeg(args: list, cwd: str = None, duration: float = None) -> tuple:
    """Запускает ffmpeg с индикатором прогресса. Возвращает (успех, текст_ошибки)."""
    cmd = [FFMPEG_PATH, "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1", "-y", *args]
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
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


# --------------------------------------------------------------- проверки

def ollama_installed_models():
    """Список установленных моделей [{name, size, family}] или None, если сервер не отвечает."""
    import ollama
    try:
        resp = ollama.list()
    except Exception:
        return None
    models = getattr(resp, "models", None)
    if models is None and isinstance(resp, dict):
        models = resp.get("models", [])
    result = []
    for m in models or []:
        if isinstance(m, dict):
            name, size = m.get("model") or m.get("name"), m.get("size")
            details = m.get("details") or {}
            family = details.get("family") if isinstance(details, dict) else getattr(details, "family", None)
        else:
            name, size = getattr(m, "model", None) or getattr(m, "name", None), getattr(m, "size", None)
            family = getattr(getattr(m, "details", None), "family", None)
        if name:
            result.append({"name": name, "size": size, "family": family or ""})
    return result


def find_ollama_exe():
    candidates = [OLLAMA_PATH, shutil.which("ollama")]
    local = os.environ.get("LOCALAPPDATA")
    if local:  # стандартное место установки на Windows
        candidates.append(os.path.join(local, "Programs", "Ollama", "ollama.exe"))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def ensure_ollama():
    """Возвращает (список_моделей, текст_проблемы). Если сервер Ollama не запущен —
    запускает его сам и ждёт готовности. Сервер остаётся работать после скрипта."""
    try:
        import ollama  # noqa: F401
    except ImportError:
        return None, "библиотека ollama не установлена  ->  pip install ollama"

    models = ollama_installed_models()
    if models is not None:
        return models, None

    exe = find_ollama_exe()
    if not exe:
        return None, ("Ollama не запущена, а программа ollama не найдена ни в PATH, ни в стандартной "
                      "папке установки. Запустите Ollama вручную или укажите путь в OLLAMA_PATH")

    print("Ollama не запущена — запускаю (ollama serve)...")
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # чтобы Ctrl+C в скрипте не убил сервер
    try:
        proc = subprocess.Popen([exe, "serve"], **kwargs)
    except OSError as e:
        return None, f"не удалось запустить Ollama ({e}). Запустите её вручную:  ollama serve"

    deadline = time.time() + OLLAMA_START_TIMEOUT
    while time.time() < deadline:
        time.sleep(1)
        models = ollama_installed_models()
        if models is not None:
            print("Ollama запущена.")
            return models, None
        if proc.poll() is not None:
            return None, ("Ollama завершилась сразу после запуска (возможно, порт занят другим "
                          "процессом). Запустите её вручную:  ollama serve")
    return None, (f"Ollama не ответила за {OLLAMA_START_TIMEOUT} с. "
                  "Запустите её вручную (ollama serve) и повторите")


def is_chat_model(m: dict) -> bool:
    """Отсекает эмбеддинг-модели (nomic-embed-text и т.п.) — переводить они не умеют."""
    return "embed" not in m["name"].lower() and "bert" not in m["family"].lower()


def format_size(size) -> str:
    return f"{size / 1e9:.1f} ГБ" if isinstance(size, (int, float)) and size else ""


def resolve_model(cli_model, installed: list):
    """Определяет модель для перевода: --model > OLLAMA_MODEL; "ask" или отсутствующая
    модель -> выбор из списка установленных."""
    global OLLAMA_MODEL
    names = [m["name"] for m in installed]
    wanted = cli_model or OLLAMA_MODEL

    if wanted != "ask":
        for candidate in (wanted, wanted + ":latest"):
            if candidate in names:
                OLLAMA_MODEL = candidate
                return
        try:  # модели нет: предлагаем скачать (спросит [Y/n]); отказ или сбой -> выбор из установленных
            ensure_ollama_model(wanted)
            installed = ollama_installed_models() or installed
            names = [m["name"] for m in installed]
            for candidate in (wanted, wanted + ":latest"):
                if candidate in names:
                    OLLAMA_MODEL = candidate
                    return
        except Exception as e:
            print(f"      {e}")

    chat_models = [m for m in installed if is_chat_model(m)]
    if not chat_models:
        print("В Ollama нет ни одной модели для перевода. Скачайте, например:  ollama pull qwen2.5:7b")
        sys.exit(1)

    if wanted != "ask":
        print(f"\nМодель {wanted} в Ollama не найдена — выберите из установленных.")

    default_idx = 1
    for i, m in enumerate(chat_models, 1):
        if m["name"] in (OLLAMA_MODEL, OLLAMA_MODEL + ":latest"):
            default_idx = i
    print("\nУстановленные модели Ollama:")
    for i, m in enumerate(chat_models, 1):
        mark = "  (по умолчанию)" if i == default_idx else ""
        print(f"  {i}. {m['name']:<28} {format_size(m['size']):>8}{mark}")
    print("Качество перевода зависит от модели: крупнее — обычно лучше, но медленнее. "
          "Модели с «рассуждением» (deepseek-r1, qwen3 и т.п.) для субтитров могут быть слишком долгими.")

    while True:
        try:
            choice = input(f"Выберите номер модели [{default_idx}]: ").strip()
        except EOFError:
            print("Не удалось спросить модель (нет ввода). Укажите её через --model или OLLAMA_MODEL.")
            sys.exit(1)
        if not choice:
            OLLAMA_MODEL = chat_models[default_idx - 1]["name"]
            return
        if choice.isdigit() and 1 <= int(choice) <= len(chat_models):
            OLLAMA_MODEL = chat_models[int(choice) - 1]["name"]
            return
        if choice in [m["name"] for m in chat_models]:
            OLLAMA_MODEL = choice
            return
        print(f"Введите номер от 1 до {len(chat_models)} или точное имя модели.")


def preflight(needs_download: bool, translator=None, compare: bool = False):
    """Проверяет, что всё нужное установлено, ДО начала долгой работы.
    Возвращает список моделей Ollama, если выбран движок ollama, иначе None."""
    problems = []

    if needs_download:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            problems.append('yt-dlp не установлен  ->  pip install -U "yt-dlp[default]"')

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        problems.append("faster-whisper не установлен  ->  pip install faster-whisper")

    try:
        subprocess.run([FFMPEG_PATH, "-version"], capture_output=True, check=True)
        if SUBTITLE_MODE == "burn" and not compare:
            r = subprocess.run([FFMPEG_PATH, "-hide_banner", "-filters"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            if not re.search(r"\bsubtitles\b", r.stdout):
                problems.append(
                    "эта сборка ffmpeg собрана без libass (нет фильтра subtitles) — вшить текст "
                    "в картинку она не сможет. Возьмите сборку с https://www.gyan.dev/ffmpeg/builds/ "
                    "или поставьте SUBTITLE_MODE = \"soft\""
                )
    except (FileNotFoundError, subprocess.CalledProcessError):
        problems.append(
            f"ffmpeg не найден ({FFMPEG_PATH}). Скачайте https://www.gyan.dev/ffmpeg/builds/ "
            "и добавьте папку bin в PATH или укажите путь в FFMPEG_PATH"
        )

    installed = None
    if translator:
        p = engine_dependency_problem(translator)
        if p:
            problems.append(p)
        elif translator == "ollama":
            installed, p = ensure_ollama()
            if p:
                problems.append(p)

    if not compare and SUBTITLE_MODE not in ("srt", "soft", "burn"):
        problems.append('режим субтитров может быть только "srt", "soft" или "burn" (в SUBTITLE_MODE допустимо ещё "ask")')

    if problems:
        print("Перед запуском нужно кое-что исправить:\n")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    return installed


# ----------------------------------------------------------- шаг 1: видео

def locate_downloaded_file(ydl, info: dict) -> str:
    for d in info.get("requested_downloads") or []:
        p = d.get("filepath") or d.get("_filename")
        if p and os.path.isfile(p):
            return p
    p = ydl.prepare_filename(info)
    if os.path.isfile(p):
        return p
    base = os.path.splitext(p)[0]
    for ext in (".mp4", ".mkv", ".webm"):
        if os.path.isfile(base + ext):
            return base + ext
    raise FileNotFoundError("скачивание завершилось, но итоговый файл не найден")


def step_download(url: str) -> str:
    from yt_dlp import YoutubeDL

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    opts = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "trim_file_name": TRIM_FILENAME_LENGTH,
        "windowsfilenames": True,
    }
    if MAX_HEIGHT:
        opts["format"] = f"bv*[height<=?{MAX_HEIGHT}]+ba/b[height<=?{MAX_HEIGHT}]"

    deno = DENO_PATH
    if not deno:  # deno.exe рядом со скриптом подхватываем сами
        for name in ("deno.exe", "deno"):
            candidate = os.path.join(SCRIPT_DIR, name)
            if os.path.isfile(candidate):
                deno = candidate
                break
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}

    if COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    elif COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get("entries"):
                info = next(e for e in info["entries"] if e)
            return locate_downloaded_file(ydl, info)
    except Exception as e:
        print(f"\nОшибка при скачивании: {e}")
        if "cookies" in str(e).lower() or "registered users" in str(e).lower():
            print("Подсказка: сайт требует вход в аккаунт — заполните COOKIES_FROM_BROWSER в CONFIG.")
        else:
            print("Подсказка: для YouTube нужен deno.exe (см. DENO_PATH); "
                  "также попробуйте обновить yt-dlp:  pip install -U yt-dlp")
        sys.exit(1)


# ------------------------------------------------- шаг 2: распознавание речи

def whisper_transcribe(media_path: str):
    """Распознаёт речь в файле. Возвращает (реплики, язык_оригинала)."""
    from faster_whisper import WhisperModel

    print("      Загружаю модель распознавания (при первом запуске скачается)...")
    model = WhisperModel(WHISPER_MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    segments, info = model.transcribe(media_path, language=LANGUAGE, vad_filter=True)
    total = getattr(info, "duration", 0) or 0

    entries = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            entries.append({
                "timecode": f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}",
                "text": text,
            })
        if total:
            print(f"\r      распознано: {min(100, seg.end / total * 100):5.1f}%", end="", flush=True)
    print()

    if not entries:
        print("Ошибка: речь в видео не обнаружена — субтитры делать не из чего.")
        sys.exit(1)
    return entries, info.language


def transcript_cache_paths(base: str):
    """Пути кэша распознавания. В имени — модель Whisper: другая модель = новое распознавание."""
    slug = re.sub(r"[^\w.-]+", "_", WHISPER_MODEL_SIZE)
    return (os.path.join(WORK_DIR, f"{base}.orig.{slug}.srt"),
            os.path.join(WORK_DIR, f"{base}.orig.{slug}.lang"))


def load_cached_transcript(base: str):
    """Возвращает (реплики, язык) из work/ или None, если кэша нет."""
    orig_srt, lang_file = transcript_cache_paths(base)
    if os.path.isfile(orig_srt) and os.path.isfile(lang_file):
        with open(lang_file, encoding="utf-8") as f:
            return read_srt(orig_srt), f.read().strip()
    return None


def step_transcribe(video_path: str, base: str):
    """Возвращает (реплики, язык_оригинала). Результат кэшируется в work/."""
    os.makedirs(WORK_DIR, exist_ok=True)

    if REUSE_INTERMEDIATE:
        cached = load_cached_transcript(base)
        if cached:
            print("      Найдено готовое распознавание — шаг пропущен (удалите папку work для пересчёта).")
            return cached

    entries, lang = whisper_transcribe(video_path)

    # кэш пишем только после полного завершения — оборванный прогон не засорит work/
    orig_srt, lang_file = transcript_cache_paths(base)
    write_srt(entries, orig_srt)
    with open(lang_file, "w", encoding="utf-8") as f:
        f.write(lang)
    return entries, lang


# ------------------------------------------------------------ шаг 3: перевод

class Progress:
    """Строка прогресса с оценкой оставшегося времени."""

    def __init__(self, label: str, total: int, quiet: bool = False):
        self.label, self.total, self.quiet, self.t0 = label, total, quiet, time.time()

    def update(self, done: int, extra: str = ""):
        if self.quiet:
            return
        eta = ""
        if done and done < self.total:
            eta = f"  (осталось ~{fmt_duration((time.time() - self.t0) / done * (self.total - done))})"
        print(f"\r      {self.label}: {done}/{self.total}{eta}{extra}        ", end="", flush=True)

    def finish(self):
        if not self.quiet:
            print()


def target_code() -> str:
    code = LANG_CODES.get(TARGET_LANGUAGE.lower())
    if not code:
        raise RuntimeError(
            f'язык перевода "{TARGET_LANGUAGE}" не поддерживается этим движком; '
            f'допустимо: {", ".join(LANG_CODES)}')
    return code


# ---- движок "ollama": обычная LLM (пачки с контекстом) -----------------------

def build_schema(n: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": n,
                "maxItems": n,
            }
        },
        "required": ["translations"],
    }


def translate_batch(lines: list, context: list) -> list:
    import ollama

    context_block = ""
    if context:
        numbered_context = "\n".join(f"- {c}" for c in context)
        context_block = (
            "Контекст предыдущих реплик (НЕ переводить повторно, только для связности):\n"
            f"{numbered_context}\n\n"
        )
    numbered_lines = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
    prompt = (
        f"Переведи субтитры на {TARGET_LANGUAGE} язык. Это реплики из видео, "
        f"переводи в разговорном, естественном стиле, сохраняя смысл и тон.\n\n"
        f"{context_block}"
        f"Реплики для перевода (ровно {len(lines)} шт., верни ровно столько же переводов "
        f"в том же порядке):\n{numbered_lines}\n\n"
        f"Верни JSON с массивом \"translations\" длиной ровно {len(lines)}."
    )
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=build_schema(len(lines)),
        options={"temperature": TEMPERATURE},
    )
    translations = json.loads(response.message.content)["translations"]
    if len(translations) != len(lines):
        raise ValueError(f"Модель вернула {len(translations)} строк вместо {len(lines)}")
    return translations


def translate_line_by_line(lines: list, context: list, stats: dict) -> list:
    """Запасной путь для пачки, не сошедшейся по числу строк: медленнее, зато
    не теряет синхронизацию с таймингом. Неудавшиеся реплики СЧИТАЮТСЯ."""
    results = []
    for line in lines:
        try:
            results.append(translate_batch([line], context)[0])
        except Exception:
            stats["failed"] += 1
            results.append(line)
    return results


def translate_ollama_generic(texts: list, lang: str, quiet: bool = False):
    translated = []
    stats = {"failed": 0, "fallback_batches": 0}
    progress = Progress("переведено", len(texts), quiet)
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        context = translated[-CONTEXT_LINES:] if translated else []
        try:
            translated.extend(translate_batch(batch, context))
        except Exception:
            stats["fallback_batches"] += 1
            translated.extend(translate_line_by_line(batch, context, stats))
        note = f"  [пачек в резервном режиме: {stats['fallback_batches']}]" if stats["fallback_batches"] else ""
        progress.update(len(translated), note)
    progress.finish()
    return translated, stats


# ---- движок "ollama" + модель TranslateGemma: свой формат запроса -----------

def is_translategemma(model: str) -> bool:
    return "translategemma" in model.lower()


def gemma_prompt(text: str, src_code: str, tgt_code: str) -> str:
    """Формат запроса, на котором обучена TranslateGemma (одно сообщение пользователя)."""
    src = LANG_NAMES_EN.get(src_code, src_code)
    tgt = LANG_NAMES_EN.get(tgt_code, tgt_code)
    return (
        f"You are a professional {src} ({src_code}) to {tgt} ({tgt_code}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {src} text "
        f"while adhering to {tgt} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {tgt} translation, without any additional explanations or commentary. "
        f"Please translate the following {src} text into {tgt}:\n\n\n{text}"
    )


def translate_gemma(texts: list, lang: str, quiet: bool = False):
    """По одной реплике: у модели нет режима 'пачки с JSON', зато формат запроса родной."""
    import ollama

    tgt = target_code()
    out = []
    stats = {"failed": 0, "fallback_batches": 0}
    progress = Progress("переведено", len(texts), quiet)
    for text in texts:
        try:
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": gemma_prompt(text.replace("\n", " "), lang, tgt)}],
                options={"temperature": TEMPERATURE},
            )
            out.append(resp.message.content.strip())
        except Exception:
            stats["failed"] += 1
            out.append(text)
        progress.update(len(out))
    progress.finish()
    return out, stats


# ---- движок "opus": компактный нейропереводчик на CTranslate2 ------------------

# Заметка: движок NLLB-200 (CTranslate2) УБРАН из скрипта — на тестах он уступал OPUS-MT и
# Gemma (китайский: «читать кардиотерапию»; японский: подставляет выдуманное «Я работал…»),
# а быстрее или точнее OPUS не был. Если понадобится вернуть как альтернативу:
#   - модель: pulkitchowdry/nllb-600m-ct2-int8 (сторонняя конвертация, int8; веса NLLB под
#     CC-BY-NC — только некоммерческое использование); грузить как OPUS:
#     hf_snapshot(репо, "model.bin") + _load_ct2(путь, путь);
#   - токенизатор грузить БЕЗ fix_mistral_regex=True (с этим флагом перевод превращается в
#     мусор; предупреждение transformers про regex можно игнорировать);
#   - язык оригинала — tokenizer.src_lang, язык перевода — target_prefix=[код] в ct2_translate()
#     (коды FLORES-200: jpn_Jpan, zho_Hans, spa_Latn, fra_Latn, deu_Latn, rus_Cyrl);
#   - переводить по предложениям и ограничивать длину ответа (ct2_translate() это уже делает).

_NMT_CACHE = {}
ENGINE_NOTES = {}


def hf_snapshot(repo: str, require_file: str = None) -> str:
    """Скачивает репозиторий с Hugging Face. У части сторонних конвертаций последняя версия
    потеряла файл весов (model.bin) — тогда ищем самый свежий коммит, где он есть."""
    from huggingface_hub import snapshot_download

    path = snapshot_download(repo)
    if require_file and not os.path.isfile(os.path.join(path, require_file)):
        from huggingface_hub import HfApi
        api = HfApi()
        for commit in api.list_repo_commits(repo):
            if require_file in api.list_repo_files(repo, revision=commit.commit_id):
                print(f"      В свежей версии {repo} нет {require_file} — беру предыдущую версию "
                      f"({commit.commit_id[:8]}).")
                return snapshot_download(repo, revision=commit.commit_id)
        raise RuntimeError(f"в репозитории {repo} нет файла {require_file} ни в одной версии")
    return path


def _load_ct2(model_dir: str, tokenizer_source: str):
    import ctranslate2
    from transformers import AutoTokenizer

    translator = ctranslate2.Translator(
        model_dir, device="cpu", compute_type="int8", intra_threads=CT2_THREADS)
    return translator, AutoTokenizer.from_pretrained(tokenizer_source)


def load_opus_pair(pair: str):
    key = "opus:" + pair
    if key not in _NMT_CACHE:
        path = hf_snapshot(OPUS_REPO_TEMPLATE.format(pair=pair), "model.bin")
        _NMT_CACHE[key] = _load_ct2(path, f"Helsinki-NLP/opus-mt-{pair}")
    return _NMT_CACHE[key]


def opus_chain(src: str, tgt: str) -> list:
    """Прямая модель пары; если её нет — цепочка через английский (src-en, en-tgt)."""
    try:
        load_opus_pair(f"{src}-{tgt}")
        return [f"{src}-{tgt}"]
    except Exception as direct_error:
        ENGINE_NOTES["opus_why"] = str(direct_error).splitlines()[0][:140]
        if "en" in (src, tgt):
            raise RuntimeError(f"модель OPUS-MT {src}-{tgt} не загрузилась: {direct_error}") from direct_error
        try:
            load_opus_pair(f"{src}-en")
            load_opus_pair(f"en-{tgt}")
        except Exception as e:
            raise RuntimeError(
                f"нет прямой модели {src}-{tgt} (причина: {direct_error}), а цепочка через "
                f"английский тоже не загрузилась: {e}. Проверьте интернет при первом запуске.") from e
        return [f"{src}-en", f"en-{tgt}"]


SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=[。！？])")


def split_sentences(text: str) -> list:
    """Реплика Whisper нередко содержит несколько предложений или обрывок; нейропереводчики,
    получив их разом, склонны терять часть текста. Переводим по предложениям."""
    flat = text.replace("\n", " ").strip()
    if not NMT_SPLIT_SENTENCES:
        return [flat]
    return [p.strip() for p in SENTENCE_SPLIT.split(flat) if p and p.strip()] or [flat]


def ct2_translate(translator, tokenizer, texts: list, target_prefix=None, progress=None) -> list:
    units, owners = [], []
    for idx, text in enumerate(texts):
        for part in split_sentences(text):
            units.append(part)
            owners.append(idx)
    if progress:
        progress.label, progress.total = progress.label + " (фраз)", len(units)

    done = []
    for start in range(0, len(units), NMT_BATCH_SIZE):
        batch = units[start:start + NMT_BATCH_SIZE]
        tokens = [tokenizer.convert_ids_to_tokens(tokenizer(t).input_ids) for t in batch]
        kwargs = {
            "beam_size": NMT_BEAM_SIZE,
            # потолок длины ответа пропорционален входу: не даёт модели зациклиться на сотни токенов
            "max_decoding_length": max(16, int(max(len(t) for t in tokens) * 2.5) + 8),
        }
        if target_prefix:
            kwargs["target_prefix"] = [[target_prefix]] * len(batch)
        for r in translator.translate_batch(tokens, **kwargs):
            hyp = list(r.hypotheses[0])
            if target_prefix and hyp and hyp[0] == target_prefix:
                hyp = hyp[1:]  # первый токен ответа — сам код языка
            done.append(tokenizer.decode(tokenizer.convert_tokens_to_ids(hyp), skip_special_tokens=True).strip())
        if progress:
            progress.update(len(done))

    parts = {i: [] for i in range(len(texts))}
    for owner, translated in zip(owners, done):
        if translated:
            parts[owner].append(translated)
    return [" ".join(parts[i]) for i in range(len(texts))]


def translate_opus(texts: list, lang: str, quiet: bool = False):
    chain = opus_chain(lang, target_code())
    ENGINE_NOTES["opus"] = " -> ".join(chain) + (
        f" (через английский; прямая пара не загрузилась: {ENGINE_NOTES.get('opus_why', '?')})"
        if len(chain) > 1 else " (прямая пара)")
    if len(chain) > 1 and not quiet:
        print("      Внимание: прямой модели OPUS-MT для этой пары нет, перевод идёт через английский — "
              "качество заметно ниже" + (" (для японского/китайского/корейского на тестах было ненадёжно; "
              "лучше Gemma)." if lang in MERGE_SKIP_LANGS else "."))
    current = texts
    for pair in chain:
        translator, tokenizer = load_opus_pair(pair)
        progress = Progress(f"переведено ({pair})", len(texts), quiet)
        current = ct2_translate(translator, tokenizer, current, None, progress)
        progress.finish()
    return current, {"failed": 0, "fallback_batches": 0}


# ---- общий вход -------------------------------------------------------------

def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return name in sys.modules


def engine_dependency_problem(engine: str):
    """Текст проблемы (чего не хватает) или None."""
    if engine == "opus":
        missing = [pip_name for mod, pip_name in (
            ("ctranslate2", "ctranslate2"), ("transformers", "transformers"),
            ("sentencepiece", "sentencepiece"), ("huggingface_hub", "huggingface_hub"),
        ) if not module_available(mod)]
        if missing:
            return f"для движка {engine} не хватает пакетов  ->  pip install {' '.join(missing)}"
    elif engine == "ollama":
        if not module_available("ollama"):
            return "библиотека ollama не установлена  ->  pip install ollama"
    return None


def translate_texts(engine: str, texts: list, lang: str, quiet: bool = False):
    """Возвращает (переводы, статистика). engine: opus | ollama."""
    if engine == "opus":
        return translate_opus(texts, lang, quiet)
    if is_translategemma(OLLAMA_MODEL):
        return translate_gemma(texts, lang, quiet)
    return translate_ollama_generic(texts, lang, quiet)


SENTENCE_END = ".!?…。！？"
CLOSING_CHARS = "\"'»”’)]』」"


def ends_sentence(text: str) -> bool:
    t = text.rstrip().rstrip(CLOSING_CHARS)
    return bool(t) and t[-1] in SENTENCE_END


def timecode_bounds(tc: str):
    """'ЧЧ:ММ:СС,ммм --> ЧЧ:ММ:СС,ммм' -> (начало, конец) в секундах или None."""
    m = re.match(r"\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", tc)
    if not m:
        return None
    g = [int(x) for x in m.groups()]
    return g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000


def extend_timecode(tc: str, other_tc: str) -> str:
    """Начало берётся из tc, конец — из other_tc."""
    return tc.split("-->")[0].strip() + " --> " + other_tc.split("-->")[1].strip()


def make_groups(entries: list) -> list:
    """Группы индексов реплик, образующие целое предложение."""
    groups, cur = [], []
    for i, e in enumerate(entries):
        if cur:
            prev, now = timecode_bounds(entries[cur[-1]]["timecode"]), timecode_bounds(e["timecode"])
            if prev and now and now[0] - prev[1] > MERGE_MAX_GAP:
                groups.append(cur)
                cur = []
        cur.append(i)
        if ends_sentence(e["text"]) or len(cur) >= MERGE_MAX_SEGMENTS:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def distribute_words(text: str, sources: list) -> list:
    """Делит перевод склеенной группы между исходными репликами пропорционально длине
    оригиналов. Если слов меньше, чем реплик, всё достаётся первой, остальные = None
    (их тайминг потом присоединяется к первой)."""
    n = len(sources)
    if n == 1:
        return [text]
    words = text.split()
    if len(words) < n:
        return [" ".join(words)] + [None] * (n - 1)
    weights = [max(1, len(x)) for x in sources]
    total, acc, prev, cuts = sum(weights), 0, 0, []
    for j in range(n - 1):
        acc += weights[j]
        cut = max(prev + 1, min(round(len(words) * acc / total), len(words) - (n - 1 - j)))
        cuts.append(cut)
        prev = cut
    bounds = [0] + cuts + [len(words)]
    return [" ".join(words[bounds[j]:bounds[j + 1]]) for j in range(n)]


def translate_aligned(entries: list, engine: str, lang: str, quiet: bool = False):
    """Возвращает (переводы по исходным репликам, статистика). Элемент результата:
    строка — перевод; "" — перевода нет (оставить оригинал); None — реплика
    присоединена к предыдущей (её тайминг входит в предыдущую)."""
    use_merge = MERGE_SENTENCES and lang not in MERGE_SKIP_LANGS
    groups = make_groups(entries) if use_merge else [[i] for i in range(len(entries))]
    texts = [" ".join(entries[i]["text"] for i in g) for g in groups]
    translated, stats = translate_texts(engine, texts, lang, quiet)

    result = [""] * len(entries)
    for g, t in zip(groups, translated):
        t = (t or "").strip()
        if not t:
            continue
        for i, part in zip(g, distribute_words(t, [entries[i]["text"] for i in g])):
            result[i] = part
    return result, {**stats, "groups": len(groups)}


def translate_entries(entries: list, engine: str, lang: str) -> list:
    parts, stats = translate_aligned(entries, engine, lang)

    out = []
    for e, part in zip(entries, parts):
        e = dict(e)
        if part is None and out:  # слово не хватило: тайминг присоединяем к предыдущей реплике
            out[-1]["timecode"] = extend_timecode(out[-1]["timecode"], e["timecode"])
            continue
        # пустой ответ модели не должен давать пустую реплику в субтитрах
        e["translated"] = (part or "").strip() or e["text"]
        out.append(e)

    total = stats.get("groups", len(entries))
    if stats["failed"]:
        print(f"      Внимание: {stats['failed']} из {total} фрагментов перевести не удалось "
              "(оставлены на языке оригинала).")
    if stats["failed"] > 0.3 * total:
        raise RuntimeError("перевод в основном не удался — проверьте, что Ollama запущена и модель скачана")
    return out


def engine_slug(engine: str) -> str:
    if engine == "ollama":
        return "ollama-" + re.sub(r"[^\w.-]+", "_", OLLAMA_MODEL)
    return engine


def engine_label(engine: str) -> str:
    return "OPUS-MT" if engine == "opus" else f"Ollama: {OLLAMA_MODEL}"


def step_translate(entries: list, lang: str, base: str) -> str:
    """Возвращает путь к .srt с переводом (в work/)."""
    os.makedirs(WORK_DIR, exist_ok=True)
    target_srt = os.path.join(WORK_DIR, f"{base}.{TARGET_LANGUAGE}.{engine_slug(TRANSLATOR)}.srt")

    if REUSE_INTERMEDIATE and os.path.isfile(target_srt):
        print("      Найден готовый перевод — шаг пропущен (удалите папку work для пересчёта).")
        return target_srt

    if lang and LANG_CODES.get(TARGET_LANGUAGE.lower()) == lang:
        print(f"      Язык оригинала уже совпадает с целевым ({lang}) — перевод не нужен.")
        write_srt(entries, target_srt)
        return target_srt

    t0 = time.time()
    try:
        entries = translate_entries(entries, TRANSLATOR, lang)
    except RuntimeError as e:
        print(f"\nОшибка: {e}")
        sys.exit(1)
    print(f"      Перевод занял {fmt_duration(time.time() - t0)}")
    write_srt(entries, target_srt, key="translated")
    return target_srt


# ------------------------------------------- шаг 4: субтитры в видео (ffmpeg)

def side_srt_path(video_path: str) -> str:
    """Куда класть .srt рядом с видео, чтобы плеер подхватил его сам. Чужие субтитры с таким
    же именем не затираем: тогда файл получает суффикс .ru.srt (VLC/PotPlayer их тоже находят)."""
    stem = os.path.splitext(video_path)[0]
    plain = stem + ".srt"
    ours = os.path.dirname(os.path.abspath(video_path)) == os.path.abspath(DOWNLOAD_DIR)
    if os.path.exists(plain) and not ours:
        return stem + "." + (LANG_CODES.get(TARGET_LANGUAGE.lower()) or "tr") + ".srt"
    return plain


def step_subtitle_video(video_path: str, srt_path: str, base: str):
    """Возвращает (файл_для_просмотра, файл_субтитров)."""
    video_path = os.path.abspath(video_path)

    if SUBTITLE_MODE == "srt":
        target = side_srt_path(video_path)
        shutil.copyfile(srt_path, target)
        return video_path, target

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    duration = get_duration(video_path)

    # отдельный .srt рядом с результатом — пригодится в любом режиме
    final_srt = os.path.join(OUTPUT_DIR, base + ".srt")
    shutil.copyfile(srt_path, final_srt)

    if SUBTITLE_MODE == "burn":
        out_path = os.path.join(OUTPUT_DIR, base + ".mp4")
        style = f"FontName={FONT_NAME},FontSize={FONT_SIZE},Outline={OUTLINE},Shadow=0,MarginV={MARGIN_V}"
        # Фильтр subtitles плохо переносит пути Windows (двоеточие после диска,
        # обратные слэши, кириллица, скобки в названии). Поэтому копируем .srt
        # во временную папку под простым именем и запускаем ffmpeg ИЗ неё.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copyfile(srt_path, os.path.join(tmp, "subs.srt"))
            ok, err = run_ffmpeg(
                ["-i", video_path,
                 "-vf", f"subtitles=subs.srt:force_style='{style}'",
                 "-map", "0:v:0", "-map", "0:a:0?",
                 "-c:v", "libx264", "-crf", str(CRF), "-preset", X264_PRESET,
                 "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", AAC_BITRATE,
                 "-movflags", "+faststart", out_path],
                cwd=tmp, duration=duration,
            )
    else:
        out_path = os.path.join(OUTPUT_DIR, base + ".mkv")
        args = ["-i", video_path, "-i", srt_path,
                "-map", "0:v:0", "-map", "0:a:0?", "-map", "1:0",
                "-c:v", "copy", "-c:a", "copy", "-c:s", "srt",
                "-disposition:s:0", "default"]
        iso3 = LANG_ISO3.get(TARGET_LANGUAGE.lower())
        if iso3:
            args += ["-metadata:s:s:0", f"language={iso3}"]
        ok, err = run_ffmpeg(args + [out_path], duration=None)

    if not ok:
        print(f"\nОшибка ffmpeg:\n{err}")
        print("Переведённые субтитры сохранены отдельно:", final_srt)
        sys.exit(1)
    return out_path, final_srt


# ------------------------------------------------------- параметры запуска

def pop_cli_option(name: str):
    """Вынимает "--name значение" или "--name=значение" из аргументов (остальные не трогает)."""
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


def resolve_mode(cli_mode):
    """Определяет итоговый режим: --mode > SUBTITLE_MODE; "ask" -> спрашивает."""
    global SUBTITLE_MODE
    if cli_mode:
        SUBTITLE_MODE = cli_mode
    if SUBTITLE_MODE != "ask":
        return
    print("\nЧто сделать с субтитрами?")
    print("  1 — srt:  только файл субтитров рядом с видео (быстрее всего; VLC/PotPlayer подхватят сами)")
    print("  2 — soft: добавить дорожкой в видео, .mkv (быстро; включается/выключается в плеере)")
    print("  3 — burn: вшить в картинку, .mp4 (работает везде, но видео перекодируется — долго)")
    while True:
        choice = ask_input("Выберите 1, 2 или 3 [1]: ").strip().lower()
        picked = {"": "srt", "1": "srt", "srt": "srt", "2": "soft", "soft": "soft",
                  "3": "burn", "burn": "burn"}.get(choice)
        if picked:
            SUBTITLE_MODE = picked
            return
        print("Введите 1, 2 или 3.")


def resolve_source():
    raw = sys.argv[1] if len(sys.argv) > 1 else ask_input("Ссылка на видео ИЛИ путь к видеофайлу: ")
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        print("Ничего не указано.")
        sys.exit(1)
    if os.path.isfile(raw):
        return "file", os.path.abspath(raw)
    if re.match(r"https?://", raw):
        return "url", raw
    print("Это не похоже ни на ссылку (http...), ни на существующий файл.")
    sys.exit(1)


def ask_input(prompt: str) -> str:
    """input() с понятной ошибкой, если интерактивного ввода нет (например, запуск из
    панели Output в VS Code или по расписанию)."""
    try:
        return input(prompt)
    except EOFError:
        print("\nНет интерактивного ввода, поэтому меню показать нельзя. Запустите скрипт в терминале "
              "(в VS Code: терминал внизу, а не панель Output / Code Runner) либо задайте значения "
              "заранее: --translator, --model, --mode или соответствующие строки в CONFIG.")
        sys.exit(1)


def pop_cli_flag(name: str) -> bool:
    """Вынимает флаг без значения (например --compare) из аргументов."""
    present = name in sys.argv[1:]
    sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != name]
    return present


def resolve_translator(cli_translator):
    """Определяет движок перевода: --translator > TRANSLATOR; "ask" -> спрашивает."""
    global TRANSLATOR
    if cli_translator:
        TRANSLATOR = cli_translator.strip().lower()
    if TRANSLATOR == "ask":
        print("\nЧем переводить субтитры?")
        print("  1 — Gemma (Ollama, translategemma): лучшее качество, единственная годная для японского;")
        print("      медленно (на старом CPU ~1 ч на 1000 реплик)")
        print("  2 — OPUS-MT: очень быстро; годится для европейских языков, для японского ненадёжен;")
        print("      лицензия Apache-2.0")
        while True:
            choice = ask_input("Выберите 1 или 2 [1]: ").strip().lower()
            picked = {"": "ollama", "1": "ollama", "ollama": "ollama", "gemma": "ollama",
                      "2": "opus", "opus": "opus"}.get(choice)
            if picked:
                TRANSLATOR = picked
                break
            print("Введите 1 или 2.")
    if TRANSLATOR == "nllb":
        print("Движок NLLB убран из скрипта: на тестах он уступал OPUS-MT и Gemma. "
              "Доступны: ollama (Gemma), opus.")
        sys.exit(1)
    if TRANSLATOR not in ("opus", "ollama"):
        print(f'Неизвестный движок перевода: "{TRANSLATOR}". Допустимо: opus, ollama, ask.')
        sys.exit(1)


# ------------------------------------------------ режим сравнения (--compare)

DEFAULT_COMPARE = ["opus", "ollama:translategemma:4b"]
COMPARE_ALIASES = {  # короткие имена для --engines и COMPARE_ENGINES
    "gemma": "ollama:translategemma:4b",
    "translategemma": "ollama:translategemma:4b",
}


def parse_compare_spec(spec: str):
    """'opus' | 'gemma' | 'ollama:<модель>' -> (движок, модель_или_None)."""
    spec = COMPARE_ALIASES.get(spec.strip().lower(), spec.strip())
    kind, _, model = spec.partition(":")
    return kind.strip().lower(), (model.strip() or None)


def parse_engines_option(value: str) -> list:
    """'opus,gemma' | 'all' -> список спецификаций без повторов."""
    result = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        for spec in (DEFAULT_COMPARE if item.lower() in ("all", "все") else [item]):
            spec = COMPARE_ALIASES.get(spec.lower(), spec)  # gemma -> ollama:translategemma:4b
            if spec not in result:
                result.append(spec)
    return result


def ensure_ollama_model(model: str):
    """Если модели нет в Ollama — предлагает скачать (с индикатором прогресса)."""
    names = [m["name"] for m in (ollama_installed_models() or [])]
    if model in names or model + ":latest" in names:
        return
    try:
        answer = input(f"Модель {model} не скачана. Скачать сейчас? [Y/n]: ").strip().lower()
    except EOFError:
        raise RuntimeError(f"модель {model} не скачана и спросить не удалось: ollama pull {model}")
    if answer in ("n", "no", "н", "нет"):
        raise RuntimeError(f"модель {model} не скачана (ollama pull {model})")

    import ollama
    print(f"      Скачиваю {model}...")
    last = -1
    for part in ollama.pull(model, stream=True):
        total, done = getattr(part, "total", None), getattr(part, "completed", None)
        if total and done is not None and int(done / total * 100) != last:
            last = int(done / total * 100)
            print(f"\r      {last}%", end="", flush=True)
    print()


def get_sample_entries(video_path: str, base: str):
    """Первые COMPARE_LINES реплик для теста. Возвращает (реплики, язык, всего_реплик_или_None)."""
    cached = load_cached_transcript(base)
    if cached:
        entries, lang = cached
        print(f"      Использую готовое распознавание ({len(entries)} реплик).")
        return entries[:COMPARE_LINES], lang, len(entries)

    print(f"      Готового распознавания нет — распознаю только первые {COMPARE_SECONDS} с видео.")
    with tempfile.TemporaryDirectory() as tmp:
        clip = os.path.join(tmp, "clip.wav")
        ok, err = run_ffmpeg(["-i", os.path.abspath(video_path), "-t", str(COMPARE_SECONDS),
                              "-vn", "-ac", "1", "-ar", "16000", clip])
        if not ok:
            print(f"Ошибка ffmpeg при вырезании фрагмента:\n{err}")
            sys.exit(1)
        entries, lang = whisper_transcribe(clip)
    return entries[:COMPARE_LINES], lang, None


def compare_one(spec: str, sample: list, lang: str) -> dict:
    global OLLAMA_MODEL
    kind, model = parse_compare_spec(spec)
    res = {"spec": spec}
    old_model = OLLAMA_MODEL
    if kind == "ollama":
        OLLAMA_MODEL = model or old_model
    if kind == "ollama":
        res["label"] = f"Ollama: {model}" if model else spec
    else:
        res["label"] = engine_label(kind) if kind == "opus" else spec
    try:
        if kind == "nllb":
            raise RuntimeError("движок nllb убран из скрипта (на тестах уступал OPUS-MT и Gemma)")
        if kind not in ("opus", "ollama"):
            raise RuntimeError(f'неизвестный движок "{spec}". Допустимо: opus, gemma, '
                               f'ollama:<модель>, all')
        if kind == "ollama" and not model:
            raise RuntimeError("для ollama укажите модель: ollama:<имя_модели>, например ollama:qwen2.5:7b")
        problem = engine_dependency_problem(kind)
        if problem:
            raise RuntimeError(problem)

        t0 = time.time()  # загрузка (при первом запуске включает скачивание моделей)
        if kind == "ollama":
            _, p = ensure_ollama()
            if p:
                raise RuntimeError(p)
            ensure_ollama_model(OLLAMA_MODEL)
        else:
            opus_chain(lang, target_code())
        res["load_s"] = time.time() - t0

        translate_aligned(sample[:1], kind, lang, quiet=True)  # прогрев: первый вызов всегда медленнее
        t1 = time.time()
        out, stats = translate_aligned(sample, kind, lang, quiet=True)
        res["run_s"] = time.time() - t1
        res["out"] = ["(слито с предыдущей)" if o is None else (o or "").strip() for o in out]
        res["failed"] = stats.get("failed", 0)
        res["note"] = ENGINE_NOTES.get(kind, "")
    except Exception as e:
        res["error"] = str(e)
    finally:
        OLLAMA_MODEL = old_model
    return res


def build_compare_report(sample: list, results: list, lang: str, total) -> str:
    lines = [f"СРАВНЕНИЕ ПЕРЕВОДЧИКОВ: {lang} -> {TARGET_LANGUAGE}, реплик в тесте: {len(sample)}", ""]
    for i, e in enumerate(sample):
        lines.append(f"[{i + 1}] {e['text']}")
        for r in results:
            if r.get("out"):
                lines.append(f"      {r['label']:<28}: {r['out'][i]}")
        lines.append("")
    lines.append("СВОДКА (время перевода без загрузки модели; на ваших данных, не из документации)")
    for r in results:
        if "error" in r:
            lines.append(f"  {r['label']:<28} НЕ ЗАПУСТИЛОСЬ — {r['error']}")
            continue
        per = r["run_s"] / max(1, len(sample))
        est = f"; на все {total} реплик ~{fmt_duration(per * total)}" if total else ""
        failed = f"; не удалось перевести: {r['failed']}" if r.get("failed") else ""
        lines.append(f"  {r['label']:<28} {per:6.2f} с/реплика{est}{failed}  | загрузка {fmt_duration(r['load_s'])}")
        if r.get("note"):
            lines.append(f"  {'':<28} ({r['note']})")
    lines.append("")
    lines.append("Загрузка при первом запуске включает скачивание моделей — для сравнения скорости")
    lines.append("смотрите колонку «с/реплика». Выбранный движок: --translator opus | ollama")
    return "\n".join(lines)


def main_compare(kind: str, source: str):
    preflight(needs_download=(kind == "url"), translator=None, compare=True)

    print("\n[1/3] Получение видео...")
    video_path = step_download(source) if kind == "url" else source
    base = os.path.splitext(os.path.basename(video_path))[0]
    print(f"      Готово: {os.path.basename(video_path)}")

    print("\n[2/3] Подготовка текста для теста...")
    sample, lang, total = get_sample_entries(video_path, base)
    if not sample:
        print("Ошибка: нет реплик для теста.")
        sys.exit(1)
    if LANG_CODES.get(TARGET_LANGUAGE.lower()) == lang:
        print(f"Язык оригинала ({lang}) совпадает с целевым — сравнивать нечего.")
        sys.exit(0)
    print(f"      Язык оригинала: {lang}; реплик в тесте: {len(sample)}")

    print("\n[3/3] Прогон движков (первый запуск может скачивать модели — это долго)...")
    results = []
    for i, spec in enumerate(COMPARE_ENGINES, 1):
        print(f"  [{i}/{len(COMPARE_ENGINES)}] {spec} ...", flush=True)
        results.append(compare_one(spec, sample, lang))
        r = results[-1]
        print(f"      {'ОШИБКА: ' + r['error'] if 'error' in r else 'готово за ' + fmt_duration(r['run_s'])}")

    report = build_compare_report(sample, results, lang, total)
    os.makedirs(WORK_DIR, exist_ok=True)
    report_path = os.path.join(WORK_DIR, f"compare_{base}_{time.strftime('%Y%m%d-%H%M%S')}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + "=" * 62)
    print(report)
    print("=" * 62)
    print(f"Отчёт сохранён: {report_path}")


# ---------------------------------------------------------------------- main

def main():
    try:  # Windows-консоль в старой кодировке иначе падает на японском/корейском тексте
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    print("=" * 62)
    print("  ВИДЕО -> ПЕРЕВОД СУБТИТРОВ -> ГОТОВОЕ ВИДЕО")
    print("=" * 62)

    compare = pop_cli_flag("--compare")
    cli_mode = (pop_cli_option("--mode") or "").lower() or None
    cli_model = pop_cli_option("--model")
    cli_translator = pop_cli_option("--translator")
    cli_engines = pop_cli_option("--engines")
    if cli_engines:
        COMPARE_ENGINES[:] = parse_engines_option(cli_engines)
    kind, source = resolve_source()

    if compare:
        main_compare(kind, source)
        return

    resolve_mode(cli_mode)
    resolve_translator(cli_translator)
    installed = preflight(needs_download=(kind == "url"), translator=TRANSLATOR)
    if TRANSLATOR == "ollama":
        resolve_model(cli_model, installed)
    t_start = time.time()

    print(f"\nРежим субтитров: {SUBTITLE_MODE} | переводчик: {engine_label(TRANSLATOR)}")

    print("\n[1/4] Получение видео...")
    video_path = step_download(source) if kind == "url" else source
    base = os.path.splitext(os.path.basename(video_path))[0]
    print(f"      Готово: {os.path.basename(video_path)}")

    print("\n[2/4] Распознавание речи (дольше всего на CPU — может занять много минут)...")
    entries, lang = step_transcribe(video_path, base)
    print(f"      Готово: {len(entries)} реплик (язык оригинала: {lang})")

    print(f"\n[3/4] Перевод субтитров на {TARGET_LANGUAGE} ({engine_label(TRANSLATOR)})...")
    srt_path = step_translate(entries, lang, base)
    print("      Готово.")

    mode_name = {"srt": "кладу файл субтитров рядом с видео", "soft": "добавляю дорожкой",
                 "burn": "вшиваю в картинку (перекодирование)"}[SUBTITLE_MODE]
    print(f"\n[4/4] Субтитры: {mode_name}...")
    final_video, final_srt = step_subtitle_video(video_path, srt_path, base)

    print("\n" + "=" * 62)
    print(f"  ВСЁ ГОТОВО за {fmt_duration(time.time() - t_start)}")
    print(f"    Видео:    {final_video}")
    print(f"    Субтитры: {final_srt}")
    if SUBTITLE_MODE == "srt":
        print("  Откройте видео в VLC или PotPlayer — русские субтитры подхватятся сами")
        print("  (если нет — перетащите .srt в окно плеера).")
    print("=" * 62)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nОстановлено пользователем (готовые шаги сохранены в work/).")
        sys.exit(1)
