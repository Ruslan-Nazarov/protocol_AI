"""Проверка черновика ответа по правилам PROTOCOL.md (8.1.4, 8.1.5, 8.1.9, 8.1.11, 8.1.15, 11.1).

Использование:
    python check_answer.py черновик.txt
    python check_answer.py черновик.txt --terms "прост(ое|ые|ых|ого)\\s+числ;нул(ь|и|ей)\\s+функци"
    python check_answer.py черновик.txt --require-tokens

Проверяет (все проверки грубые: находят подозрительные места, не доказывают правильность):
1. Ссылки вперёд (8.1.4).
2. Термин без признака определения в предложении первого употребления (--terms).
3. Оценочные слова без пояснения (8.1.11): «очевидно», «быстро», «почти» и т.п.
4. Слова, зависящие от контекста (8.1.5): «остальные», «такие» и т.п.
5. Длина абзаца (8.1.15): больше 80 слов или 5 предложений.
6. Формула без сопровождающей прозы в абзаце (8.1.9): абзац, где формульные
   предложения есть, а обычных (прозаических) — нет.
7. --require-tokens: есть ли в тексте строка с отчётом о расходе токенов (11.1).
Код возврата: 0 — замечаний нет, 1 — есть замечания.
"""
import re
import sys

FORWARD_MARKERS = [
    r"\bниже\b", r"(?<!так\s)\bдалее\b", r"\bпозже\b", r"\bпозднее\b", r"\bдальше\b",
    r"\bпотом\b", r"\bвпоследствии\b", r"в\s+дальнейшем", r"как\s+увидим",
    r"\bувидим\b", r"\bувидите\b", r"будет\s+понятно", r"станет\s+(понятно|ясно)",
    r"об\s+этом\s+(позже|ниже|дальше)", r"\bподробнее\b",
    r"в\s+следующ\w+\s+(шаге|разделе|части|блоке)", r"\bсм\.", r"смотр\w+\s+ниже",
]
VAGUE_WORDS = [r"очевидн\w*", r"\bпочти\b", r"\bбыстро\b", r"\bлегко\b", r"\bпросто\b", r"\bясно\b", r"нетрудно", r"несложно", r"как\s+известно"]
# English equivalents apply the same heuristic checks to English drafts.
FORWARD_MARKERS += [r"\bbelow\b", r"\blater\b", r"\bsubsequently\b", r"\bas we (?:will|shall) see\b", r"\bin the next (?:step|section|part|block)\b"]
VAGUE_WORDS += [r"\bobvious(?:ly)?\b", r"\balmost\b", r"\bquickly\b", r"\beasily\b", r"\bsimply\b", r"\bclearly\b", r"\bas is known\b"]
MAX_WORDS = 80
MAX_SENTENCES = 5
CONTEXT_WORDS =[r"\bостальн\w+", r"\bпрочи\w+", r"\bтакие\b", r"\bтакой\b", r"\bтакая\b", r"\bтакое\b"]
DEFINITION_CUES =[r"\s—\s", r"\bэто\b", r"называется", r"называют", r"\(", r":"]
CONTEXT_WORDS += [r"\bremaining\b", r"\bsuch\b", r"\bthese\b", r"\bthe rest\b"]
DEFINITION_CUES += [r"\bis\b", r"\bare\b", r"\bmeans\b", r"\bcalled\b", r"\bdefined as\b"]
TOKEN_REPORT = r"токен|\btokens?\b"
MATH_CHARS = set("=+*/^∑∏∫≤≥≈≠<>∈∉∞²³ˢᵃᵇⁿ⁻⁺·")


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def is_formula_heavy(sentence):
    letters = re.findall(r"[А-Яа-яЁёA-Za-z]", sentence)
    cyr_words = re.findall(r"[А-Яа-яЁё]{3,}", sentence)
    math_count = sum(1 for ch in sentence if ch in MATH_CHARS)
    return math_count >= 2 and len(cyr_words) <= 2 and len(letters) < len(sentence) * 0.4


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    language = args[args.index('--language')+1] if '--language' in args else 'ru'
    def message(ru, en):
        return en if language == 'en' else ru
    path = args[0]
    terms = []
    if "--terms" in args:
        terms = [t for t in args[args.index("--terms") + 1].split(";") if t.strip()]
    require_tokens = "--require-tokens" in args
    text = open(path, encoding="utf-8").read()
    sentences = split_sentences(text)
    problems = 0

    if require_tokens and not re.search(TOKEN_REPORT, text, flags=re.IGNORECASE):
        problems += 1
        print(message("[НЕТ ОТЧЁТА О ТОКЕНАХ] по 11.1 ожидается строка с упоминанием токенов", "[NO TOKEN REPORT] 11.1 requires a line mentioning token usage"))

    for j, para in enumerate([p for p in re.split(r"\n\s*\n", text) if p.strip()], 1):
        n_words = len(para.split())
        para_sentences = split_sentences(para)
        n_sent = len(para_sentences)
        if n_words > MAX_WORDS or n_sent > MAX_SENTENCES:
            problems += 1
            print(message("[ДЛИННЫЙ АБЗАЦ] абзац %d: %d слов, %d предложений (порог %d слов, %d предложений)", "[LONG PARAGRAPH] paragraph %d: %d words, %d sentences (limit: %d words, %d sentences)")
                  % (j, n_words, n_sent, MAX_WORDS, MAX_SENTENCES))
        formula_flags = [is_formula_heavy(s) for s in para_sentences]
        if formula_flags and all(formula_flags):
            problems += 1
            print(message("[ФОРМУЛА БЕЗ ПРОЗЫ?] абзац %d: все предложения формульные, нет объяснения словами (8.1.9)", "[FORMULA WITHOUT PROSE?] paragraph %d: all sentences are formulas, with no verbal explanation (8.1.9)") % j)

    for i, s in enumerate(sentences, 1):
        for m in FORWARD_MARKERS:
            if re.search(m, s, flags=re.IGNORECASE):
                problems += 1
                print(message("[ССЫЛКА ВПЕРЁД] предложение %d: %s", "[FORWARD REFERENCE] sentence %d: %s") % (i, s))
                break

    for i, s in enumerate(sentences, 1):
        for m in VAGUE_WORDS:
            if re.search(m, s, flags=re.IGNORECASE):
                problems += 1
                print(message("[ОЦЕНОЧНОЕ СЛОВО БЕЗ ПОЯСНЕНИЯ?] предложение %d: %s", "[VAGUE WORD WITHOUT EXPLANATION?] sentence %d: %s") % (i, s))
                break

    for i, s in enumerate(sentences, 1):
        for m in CONTEXT_WORDS:
            if re.search(m, s, flags=re.IGNORECASE):
                problems += 1
                print(message("[СЛОВО ЗАВИСИТ ОТ КОНТЕКСТА?] предложение %d: %s", "[CONTEXT-DEPENDENT WORD?] sentence %d: %s") % (i, s))
                break

    for t in terms:
        rx = re.compile(t, flags=re.IGNORECASE)
        for i, s in enumerate(sentences, 1):
            if rx.search(s):
                if not any(re.search(c, s, flags=re.IGNORECASE) for c in DEFINITION_CUES):
                    problems += 1
                    print(message("[ТЕРМИН БЕЗ ОПРЕДЕЛЕНИЯ?] '%s' впервые в предложении %d: %s", "[TERM WITHOUT DEFINITION?] '%s' first occurs in sentence %d: %s") % (t, i, s))
                break
        else:
            print(message("[ТЕРМИН НЕ НАЙДЕН] '%s'", "[TERM NOT FOUND] '%s'") % t)

    print(message("Замечаний: %d", "Warnings: %d") % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
