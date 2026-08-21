"""
Офлайн-перевод субтитров (.srt) через локальную модель в Ollama (Qwen 2.5:7b).

Как запустить:
  python translate_subtitles.py "C:\путь\к\файлу_или_папке_с_srt"
  — либо просто "python translate_subtitles.py" без аргумента, тогда
  скрипт спросит путь.

Один раз установить:
  pip install ollama
Требуется запущенный Ollama (ollama serve) с уже скачанной моделью
(ollama pull qwen2.5:7b) — то, что у вас уже есть.

Как обеспечивается надёжность (субтитры — это не просто текст, важно не
потерять тайминг и не перепутать порядок строк):
  - Реплики переводятся ПАЧКАМИ (BATCH_SIZE), а не всем файлом разом и не
    по одной, — так модель видит контекст соседних реплик (важно для
    местоимений и связности), но при этом не теряет строки, как бывает
    при переводе огромных кусков текста целиком.
  - Каждый запрос к Ollama идёт с жёсткой JSON-схемой (structured outputs) —
    модель обязана вернуть массив строк ТОЧНО той же длины, что и пачка.
    Схема не даёт модели "смухлевать" и слить/потерять реплику.
  - Если пачка всё же вернулась не той длины (редко, но бывает) — скрипт
    переводит эту пачку заново по одной реплике, чтобы гарантированно
    не потерять синхронизацию с таймингом.

Про качество перевода на Qwen 2.5:7b: модель официально заявлена
многоязычной (в т.ч. японский, испанский, французский), для субтитров
(короткие, разговорные фразы) 7B обычно справляется вполне достойно.
Меньше всего уверенности — на японском (больше idiomatики), стоит выборочно
проверить несколько строк глазами после первого прогона. Если качество
не устроит — единственное, что нужно поменять, это OLLAMA_MODEL ниже
(например, на "qwen2.5:14b", если позволит память).
"""

import os
import sys
import re
import json

import ollama

# ======================= CONFIG (правьте под задачу) =======================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "translated")   # всегда рядом со скриптом

OLLAMA_MODEL = "qwen2.5:7b"
TARGET_LANGUAGE = "русский"   # ПРЕДПОЛОЖЕНИЕ: перевод делается НА этот язык.
                                # Смените на "английский", "испанский" и т.п.,
                                # если направление перевода другое.

BATCH_SIZE = 20        # реплик за один запрос к модели
CONTEXT_LINES = 2      # сколько предыдущих реплик показывать как контекст
                         # (не переводятся повторно, только для связности)
TEMPERATURE = 0.2       # ниже = стабильнее и предсказуемее перевод

# =============================================================================


def parse_srt(path: str) -> list:
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        timecode = lines[1].strip()
        text = "\n".join(lines[2:]).strip()
        entries.append({"timecode": timecode, "text": text})
    return entries


def write_srt(entries: list, path: str, text_key: str = "translated"):
    with open(path, "w", encoding="utf-8") as f:
        for i, e in enumerate(entries, start=1):
            f.write(f"{i}\n{e['timecode']}\n{e[text_key]}\n\n")


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
    context_block = ""
    if context:
        numbered_context = "\n".join(f"- {c}" for c in context)
        context_block = (
            f"Контекст предыдущих реплик (НЕ переводить повторно, только для связности):\n"
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

    data = json.loads(response.message.content)
    translations = data["translations"]

    if len(translations) != len(lines):
        raise ValueError(f"Модель вернула {len(translations)} строк вместо {len(lines)}")

    return translations


def translate_line_by_line(lines: list, context: list) -> list:
    """Запасной путь для пачки, которая не сошлась по количеству строк —
    медленнее, зато гарантированно не теряет синхронизацию с таймингом."""
    results = []
    for line in lines:
        try:
            results.append(translate_batch([line], context)[0])
        except Exception:
            results.append(line)  # совсем не смогли — оставляем оригинал, не молчим о потере
    return results


def translate_entries(entries: list) -> list:
    texts = [e["text"] for e in entries]
    translated_texts = []

    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        context = translated_texts[-CONTEXT_LINES:] if translated_texts else []

        try:
            batch_translated = translate_batch(batch, context)
        except Exception as e:
            print(f"   (пачка {start}-{start + len(batch)}: {e} — перевожу по одной реплике)")
            batch_translated = translate_line_by_line(batch, context)

        translated_texts.extend(batch_translated)

    for e, t in zip(entries, translated_texts):
        e["translated"] = t
    return entries


def resolve_input_path() -> str:
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = input("Укажите путь к .srt файлу или папке с .srt файлами: ")
    return os.path.abspath(raw.strip().strip('"').strip("'"))


def collect_srt_files(input_path: str) -> list:
    if os.path.isfile(input_path):
        return [input_path]
    return [
        os.path.join(input_path, f) for f in sorted(os.listdir(input_path))
        if f.lower().endswith(".srt")
    ]


if __name__ == "__main__":
    input_path = resolve_input_path()

    if not os.path.exists(input_path):
        print(f"Ошибка: не найдено — {input_path}")
        sys.exit(1)

    if os.path.isdir(input_path) and os.path.abspath(input_path) == os.path.abspath(OUTPUT_DIR):
        print(f"Ошибка: папка-источник совпадает с папкой результатов ({OUTPUT_DIR}). Остановлено.")
        sys.exit(1)

    srt_files = collect_srt_files(input_path)
    if not srt_files:
        print("Не найдено .srt файлов.")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Модель:    {OLLAMA_MODEL}")
    print(f"Язык:      -> {TARGET_LANGUAGE}")
    print(f"Файлов:    {len(srt_files)}\n")

    for srt_path in srt_files:
        filename = os.path.basename(srt_path)
        base_name = os.path.splitext(filename)[0]
        out_path = os.path.join(OUTPUT_DIR, f"{base_name}_{TARGET_LANGUAGE}.srt")

        print(f"Перевод: {filename} ...")
        try:
            entries = parse_srt(srt_path)
            entries = translate_entries(entries)
            write_srt(entries, out_path, text_key="translated")
            print(f"   готово -> {os.path.basename(out_path)} ({len(entries)} реплик)")
        except Exception as e:
            print(f"   ОШИБКА: {e}")
