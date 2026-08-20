# Morphology-aware keyword matching + CSV export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace LLM-based keyword matching with local deterministic stem matching (`snowballstemmer`), add OR-logic for multiple keywords, and add server-side CSV export.

**Architecture:** New pure-function module `app/keyword_match.py` does all keyword logic locally. The LLM prompt no longer asks for `has_keyword`/`keyword_found`. `app/scraper.py` calls the new module after fetching text. A cache-key version bump in `app/analyzer.py` invalidates stale cached entries. CSV is a pure serializer in `app/report.py` served by a new endpoint.

**Tech Stack:** Python 3.13, FastAPI, snowballstemmer, Jinja2, pytest (for records; verify via `python -c`)

**Spec:** `docs/superpowers/specs/2026-08-12-keyword-matching-csv-export-design.md`

## Global Constraints

- pytest hangs on this Windows/Python 3.13 machine — **never run `python -m pytest`**. Verify via `.\venv\Scripts\python.exe -c "..."` or throwaway scripts.
- `httpx<0.28`, `pytest<9` (version pinning in `requirements.txt`)
- Python 3.13, Pydantic v2, SQLAlchemy async + aiosqlite
- All paths are relative to `cultural-history-app/`
- Do not commit `.env`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/keyword_match.py` | **Create** | `tokenize`, `_stem`, `match_keywords`, `has_keyword` |
| `tests/test_keyword_match.py` | **Create** | Pure-function tests for keyword matching |
| `app/llm.py` | **Modify** | Remove `has_keyword`/`keyword_found` from prompt JSON contract |
| `app/scraper.py` | **Modify** | Import and call `match_keywords` after LLM call |
| `app/analyzer.py` | **Modify** | Bump `_cache_keywords` format with `#kwv2` marker |
| `app/report.py` | **Modify** | Add `report_to_csv` pure function |
| `app/main.py` | **Modify** | Add `GET /results/{task_id}/csv` endpoint |
| `app/templates/results.html` | **Modify** | Add «Сохранить в CSV» link |
| `requirements.txt` | **Modify** | Add `snowballstemmer>=2.2` |
| `AGENTS.md` | **Modify** | Note new module in architecture section |

---

### Task 1: keyword_match module + tests

**Files:**
- Create: `app/keyword_match.py`
- Create: `tests/test_keyword_match.py`

**Interfaces:**
- Consumes: none (standalone)
- Produces: `tokenize(text) -> list[str]`, `_stem(token) -> str`, `match_keywords(text, keywords: list[str]) -> list[str]`, `has_keyword(text, keywords: list[str]) -> bool`

- [ ] **Step 1: Install snowballstemmer**

```bash
.\venv\Scripts\pip.exe install snowballstemmer>=2.2
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_keyword_match.py`:

```python
from app.keyword_match import tokenize, match_keywords, has_keyword


def test_tokenize_splits_words():
    assert tokenize("Привет мир 123") == ["привет", "мир", "123"]


def test_tokenize_lowercases():
    assert tokenize("Византия") == ["византия"]


def test_single_keyword_morphology():
    text = "Говорим о Византии и её наследии"
    assert match_keywords(text, ["Византия"]) == ["Византия"]


def test_single_keyword_no_match():
    text = "Совсем другой текст без ключевых слов"
    assert match_keywords(text, ["Византия"]) == []


def test_multiple_keywords_or_logic():
    text = "Здесь упоминается только один объект"
    result = match_keywords(text, ["Византия", "Константинополь"])
    assert len(result) == 1
    assert result[0] == "Византия"


def test_multiple_keywords_both_match():
    text = "Византия и Конstantinополь — это важно"
    result = match_keywords(text, ["Византия", "Константинополь"])
    assert len(result) == 2


def test_has_keyword_true():
    assert has_keyword("Византии", ["Византия"]) is True


def test_has_keyword_false():
    assert has_keyword("Пустой текст", ["Византия"]) is False


def test_phrase_keyword_contiguous():
    text = "Мы посетили Новый Год в этом году"
    assert match_keywords(text, ["Новый Год"]) == ["Новый Год"]


def test_phrase_keyword_separated():
    text = "Год был очень новым и интересным"
    assert match_keywords(text, ["Новый Год"]) == []


def test_latin_keyword():
    text = "The Byzantine Empire was great"
    assert match_keywords(text, ["Byzantine"]) == ["Byzantine"]


def test_empty_keywords():
    assert match_keywords("text", []) == []


def test_pure_punctuation_keyword():
    assert match_keywords("hello world", ["..."]) == []
```

- [ ] **Step 3: Run test to verify it fails**

```bash
.\venv\Scripts\python.exe -c "from app.keyword_match import tokenize; print('import ok')"
```

Expected: `ModuleNotFoundError` — module does not exist yet.

- [ ] **Step 4: Write minimal implementation**

Create `app/keyword_match.py`:

```python
import re
from snowballstemmer import stemmer

_token_re = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_cyrillic_re = re.compile(r"[а-яё]")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _token_re.findall(text)]


def _stem(token: str) -> str:
    lower = token.lower()
    if _cyrillic_re.search(lower):
        return stemmer("russian").stemWord(lower)
    if lower.isascii() and lower.isalpha():
        return stemmer("english").stemWord(lower)
    return lower


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    page_stems = [_stem(t) for t in tokenize(text)]
    matched = []
    for kw in keywords:
        kw_tokens = tokenize(kw)
        if not kw_tokens:
            continue
        kw_stems = [_stem(t) for t in kw_tokens]
        kw_len = len(kw_stems)
        for i in range(len(page_stems) - kw_len + 1):
            if page_stems[i : i + kw_len] == kw_stems:
                matched.append(kw)
                break
    return matched


def has_keyword(text: str, keywords: list[str]) -> bool:
    return bool(match_keywords(text, keywords))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.\venv\Scripts\python.exe -c "
from app.keyword_match import tokenize, match_keywords, has_keyword

assert tokenize('Привет мир 123') == ['привет', 'мир', '123']
assert tokenize('Византия') == ['византия']

assert match_keywords('Говорим о Византии и её наследии', ['Византия']) == ['Византия']
assert match_keywords('Совсем другой текст', ['Византия']) == []

result = match_keywords('Здесь упоминается только один объект', ['Византия', 'Константинополь'])
assert len(result) == 1 and result[0] == 'Византия'

assert has_keyword('Византии', ['Византия']) is True
assert has_keyword('Пустой текст', ['Византия']) is False

assert match_keywords('Мы посетили Новый Год', ['Новый Год']) == ['Новый Год']
assert match_keywords('Год был очень новым', ['Новый Год']) == []
assert match_keywords('The Byzantine Empire', ['Byzantine']) == ['Byzantine']
assert match_keywords('text', []) == []
assert match_keywords('hello world', ['...']) == []

print('ALL PASS')
"
```

Expected: `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add cultural-history-app/app/keyword_match.py cultural-history-app/tests/test_keyword_match.py
git commit -m "feat: add morphology-aware keyword matching module"
```

---

### Task 2: Remove keyword fields from LLM prompt

**Files:**
- Modify: `app/llm.py` (prompt at line 20-31, fallback dict at line 128-137)
- Modify: `tests/test_llm.py` (add prompt contract test)

**Interfaces:**
- Consumes: none (standalone change)
- Produces: LLM no longer returns `has_keyword`/`keyword_found`; `_coerce_result` still tolerates their absence

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm.py`:

```python
def test_build_prompt_excludes_keyword_fields():
    prompt = _build_prompt("Monastery", ["Byzantium"], "Title", "Text")
    assert "has_keyword" not in prompt
    assert "keyword_found" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.\venv\Scripts\python.exe -c "
from app.llm import _build_prompt
prompt = _build_prompt('M', ['K'], 'T', 'X')
assert 'has_keyword' not in prompt, 'FAIL: has_keyword still in prompt'
"
```

Expected: `AssertionError: FAIL: has_keyword still in prompt`

- [ ] **Step 3: Modify the prompt**

In `app/llm.py`, `_build_prompt` (lines 11-32), change the prompt to:

```python
def _build_prompt(object_name: str, keywords: list[str], title: str, text: str) -> str:
    keywords_str = ", ".join(keywords)
    return (
        f'Analyze the text below. Determine if "{object_name}" is mentioned, '
        f'and extract dates and author location.\n\n'
        f"Object: {object_name}\n"
        f"Keywords (for relevance context only): {keywords_str}\n\n"
        f"Title: {title}\n\n"
        f"Text: {text[:3000]}\n\n"
        "Respond in JSON format only:\n"
        '{\n'
        '  "mentions_object": true/false,\n'
        '  "object_name": "name from text or null",\n'
        '  "date_mentioned": "DD.MM.YYYY from text or null",\n'
        '  "publication_date": "DD.MM.YYYY or null",\n'
        '  "author_location": "city, country, region or null",\n'
        '  "relevance_score": 0.0-1.0,\n'
        '  "source_type": "blog/forum/social/official/agency/other"\n'
        "}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.\venv\Scripts\python.exe -c "
from app.llm import _build_prompt
prompt = _build_prompt('M', ['K'], 'T', 'X')
assert 'has_keyword' not in prompt
assert 'keyword_found' not in prompt
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/llm.py cultural-history-app/tests/test_llm.py
git commit -m "feat: remove has_keyword/keyword_found from LLM prompt contract"
```

---

### Task 3: Integrate local keyword matching in scraper

**Files:**
- Modify: `app/scraper.py` (import + call after LLM)

**Interfaces:**
- Consumes: `match_keywords(text, keywords)` from `app/keyword_match.py`
- Produces: `has_keyword` and `keyword_found` on result dict set locally, not by LLM

- [ ] **Step 1: Write the failing test (throwaway script)**

Create and run a throwaway verification script:

```python
# throwaway_test_scraper_integration.py
import asyncio
import sys
sys.path.insert(0, "cultural-history-app")

from unittest.mock import patch, AsyncMock

async def test():
    from app.scraper import fetch_and_analyze

    fake_llm_result = {
        "mentions_object": True,
        "date_mentioned": None,
        "publication_date": "2025",
        "author_location": None,
        "relevance_score": 0.8,
        "source_type": "blog",
    }

    with patch("app.scraper.fetch_page_text", new_callable=AsyncMock) as mock_fetch, \
         patch("app.scraper.analyze_text_with_retry", new_callable=AsyncMock) as mock_llm:
        mock_fetch.return_value = "Говорим о Византии и её наследии"
        mock_llm.return_value = fake_llm_result

        result = await fetch_and_analyze(
            "https://example.com", "Монастырь", ["Византия"], "Title"
        )
        assert result["has_keyword"] is True, f"Expected True, got {result['has_keyword']}"
        assert result["keyword_found"] == "Византия", f"Expected 'Византия', got {result['keyword_found']}"
        print("PASS: local keyword matching works")

asyncio.run(test())
```

Run:

```bash
.\venv\Scripts\python.exe throwaway_test_scraper_integration.py
```

Expected: `FAIL` — `fetch_and_analyze` currently does not import or call `match_keywords`.

- [ ] **Step 2: Modify scraper.py**

In `app/scraper.py`, add import at top (after line 6):

```python
from app.keyword_match import match_keywords
```

In `fetch_and_analyze` (lines 45-72), after `llm_result["raw_text_hash"] = h` (line 71), add keyword matching:

```python
    matched = match_keywords(text, keywords)
    llm_result["has_keyword"] = bool(matched)
    llm_result["keyword_found"] = ", ".join(matched) if matched else None
    return llm_result
```

- [ ] **Step 3: Run throwaway test to verify it passes**

```bash
.\venv\Scripts\python.exe throwaway_test_scraper_integration.py
```

Expected: `PASS: local keyword matching works`

- [ ] **Step 4: Clean up throwaway script**

```bash
Remove-Item throwaway_test_scraper_integration.py
```

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/scraper.py
git commit -m "feat: use local keyword matching in fetch_and_analyze"
```

---

### Task 4: Bump cache key version

**Files:**
- Modify: `app/analyzer.py` (`_cache_keywords` at line 38-39)

**Interfaces:**
- Consumes: none (internal)
- Produces: `_cache_keywords` returns format with `#kwv2` suffix

- [ ] **Step 1: Verify current behavior**

```bash
.\venv\Scripts\python.exe -c "
from app.analyzer import _cache_keywords
old = _cache_keywords(['a', 'b'])
assert old == 'a,b', f'Unexpected: {old}'
print(f'Current format: {old!r}')
"
```

Expected: `Current format: 'a,b'`

- [ ] **Step 2: Modify _cache_keywords**

In `app/analyzer.py`, line 38-39, change:

```python
def _cache_keywords(keywords):
    return ",".join(keywords) + "#kwv2"
```

- [ ] **Step 3: Verify new format**

```bash
.\venv\Scripts\python.exe -c "
from app.analyzer import _cache_keywords
new = _cache_keywords(['a', 'b'])
assert new == 'a,b#kwv2', f'Unexpected: {new}'
assert new != 'a,b', 'Should differ from old format'
print('PASS')
"
```

Expected: `PASS`

- [ ] **Step 4: Commit**

```bash
git add cultural-history-app/app/analyzer.py
git commit -m "feat: bump cache key format to kwv2 to invalidate stale entries"
```

---

### Task 5: CSV serializer in report.py

**Files:**
- Modify: `app/report.py` (add `report_to_csv` function)

**Interfaces:**
- Consumes: `ReportData` from `app/schemas.py`
- Produces: `report_to_csv(report: ReportData) -> str`

- [ ] **Step 1: Write the failing test (throwaway script)**

```python
# throwaway_test_csv.py
import sys
sys.path.insert(0, "cultural-history-app")

from app.report import report_to_csv
from app.schemas import ReportData, AnalysisResult

report = ReportData(
    task_id="t1",
    object_name="Монастырь",
    keywords="Византия",
    annual_visitors=None,
    total_mentions=2,
    mentions_with_keyword=1,
    keyword_percentage=50.0,
    percentage_of_visitors=None,
    results=[
        AnalysisResult(
            url="https://example.com/1",
            title="Статья 1",
            mentions_object=True,
            has_keyword=True,
            keyword_found="Византия",
            date_mentioned="15.03.2025",
            publication_date=None,
            author_location="Москва",
            relevance_score=0.9,
            source_type="blog",
        ),
        AnalysisResult(
            url="https://example.com/2",
            title="Статья 2",
            mentions_object=False,
            has_keyword=False,
            keyword_found=None,
            date_mentioned=None,
            publication_date="2024",
            author_location=None,
            relevance_score=0.1,
            source_type="official",
        ),
    ],
    status="completed",
    search_engine="searxng",
)

csv_str = report_to_csv(report)

# Check BOM
assert csv_str.startswith("\ufeff"), "Missing BOM"

lines = csv_str.lstrip("\ufeff").strip().split("\r\n")
assert len(lines) == 3, f"Expected 3 lines (header + 2 data), got {len(lines)}"

header = lines[0]
assert ";" in header, "Missing semicolon delimiter"
assert "№" in header
assert "URL" in header
assert "Упоминает объект" in header

row1 = lines[1]
assert "да" in row1
assert "Византия" in row1

row2 = lines[2]
assert "нет" in row2

# Empty report
empty = ReportData(
    task_id="t2", object_name="X", keywords="Y",
    annual_visitors=None, total_mentions=0, mentions_with_keyword=0,
    keyword_percentage=0.0, percentage_of_visitors=None, results=[],
)
empty_csv = report_to_csv(empty)
empty_lines = empty_csv.lstrip("\ufeff").strip().split("\r\n")
assert len(empty_lines) == 1, "Empty report should have header only"

print("ALL PASS")
```

Run:

```bash
.\venv\Scripts\python.exe throwaway_test_csv.py
```

Expected: `ModuleNotFoundError` or `ImportError` — `report_to_csv` does not exist yet.

- [ ] **Step 2: Implement report_to_csv**

In `app/report.py`, add at top:

```python
import csv
import io
```

Append to end of file:

```python
def report_to_csv(report: ReportData) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow([
        "№", "URL", "Заголовок", "Источник", "Ключевые слова",
        "Дата", "Геопривязка", "Релевантность", "Упоминает объект",
    ])
    for i, r in enumerate(report.results, 1):
        date_val = r.publication_date or r.date_mentioned or ""
        mentions_val = "да" if r.mentions_object else "нет"
        writer.writerow([
            i,
            r.url,
            r.title or "",
            r.source_type or "",
            r.keyword_found or "",
            date_val,
            r.author_location or "",
            r.relevance_score,
            mentions_val,
        ])
    return "\ufeff" + buf.getvalue()
```

- [ ] **Step 3: Run test to verify it passes**

```bash
.\venv\Scripts\python.exe throwaway_test_csv.py
```

Expected: `ALL PASS`

- [ ] **Step 4: Clean up throwaway script**

```bash
Remove-Item throwaway_test_csv.py
```

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/report.py
git commit -m "feat: add report_to_csv serializer (BOM, semicolon delimiter)"
```

---

### Task 6: CSV endpoint in main.py

**Files:**
- Modify: `app/main.py` (add endpoint + import Response)

**Interfaces:**
- Consumes: `build_report` (existing), `report_to_csv` (from Task 5)
- Produces: `GET /results/{task_id}/csv` returning CSV download

- [ ] **Step 1: Add import**

In `app/main.py`, line 8, add `Response` to the imports:

```python
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
```

- [ ] **Step 2: Add import for report_to_csv**

After line 17 (`from app.report import build_report`), change to:

```python
from app.report import build_report, report_to_csv
```

- [ ] **Step 3: Add the endpoint**

Before the `if __name__` block (before line 149), add:

```python
@app.get("/results/{task_id}/csv")
async def download_csv(task_id: str, db: AsyncSession = Depends(get_db)):
    report = await build_report(task_id, db)
    if report is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    csv_bytes = report_to_csv(report).encode("utf-8")
    return Response(
        csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="report_{task_id}.csv"'},
    )
```

- [ ] **Step 4: Verify import works**

```bash
.\venv\Scripts\python.exe -c "from app.main import download_csv; print('PASS')"
```

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add cultural-history-app/app/main.py
git commit -m "feat: add GET /results/{task_id}/csv endpoint"
```

---

### Task 7: Frontend — add CSV download link

**Files:**
- Modify: `app/templates/results.html` (line 77)

**Interfaces:**
- Consumes: `report.task_id` (existing)
- Produces: «Сохранить в CSV» link on results page

- [ ] **Step 1: Modify results.html**

In `app/templates/results.html`, line 77, change:

```html
<a href="/">Новый анализ</a>
```

to:

```html
<a href="/results/{{ report.task_id }}/csv" download>Сохранить в CSV</a>
<a href="/">Новый анализ</a>
```

- [ ] **Step 2: Commit**

```bash
git add cultural-history-app/app/templates/results.html
git commit -m "feat: add CSV download link to results page"
```

---

### Task 8: requirements.txt + AGENTS.md

**Files:**
- Modify: `requirements.txt`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add snowballstemmer to requirements.txt**

In `requirements.txt`, add after line 12 (`beautifulsoup4>=4.12.0`):

```
snowballstemmer>=2.2
```

- [ ] **Step 2: Update AGENTS.md architecture notes**

In `AGENTS.md`, after the line about `app/source_type.py` `classify_source()`, add:

```
- Keyword matching is local and deterministic (`app/keyword_match.py`): `snowballstemmer` stems page + keyword tokens, matches by contiguous subsequence. Multi-keyword logic is OR (at least one match)
```

- [ ] **Step 3: Commit**

```bash
git add cultural-history-app/requirements.txt AGENTS.md
git commit -m "docs: add snowballstemmer dep and keyword matching to AGENTS.md"
```

---

### Task 9: Final verification

- [ ] **Step 1: Verify all imports work**

```bash
.\venv\Scripts\python.exe -c "
from app.keyword_match import tokenize, match_keywords, has_keyword
from app.llm import _build_prompt, _coerce_result
from app.scraper import fetch_and_analyze
from app.analyzer import _cache_keywords
from app.report import build_report, report_to_csv
from app.main import download_csv
print('ALL IMPORTS OK')
"
```

- [ ] **Step 2: Verify keyword matching end-to-end**

```bash
.\venv\Scripts\python.exe -c "
from app.keyword_match import has_keyword, match_keywords
assert has_keyword('Византии', ['Византия']) is True
assert match_keywords('Византии', ['Византия']) == ['Византия']
assert has_keyword('пустой', ['Византия']) is False
assert match_keywords('одна', ['А', 'Б']) == []
assert match_keywords('А есть', ['А', 'Б']) == ['А']
print('END-TO-END PASS')
"
```

- [ ] **Step 3: Verify CSV serialization**

```bash
.\venv\Scripts\python.exe -c "
from app.report import report_to_csv
from app.schemas import ReportData, AnalysisResult
r = ReportData(
    task_id='t', object_name='o', keywords='k', annual_visitors=None,
    total_mentions=1, mentions_with_keyword=1, keyword_percentage=100.0,
    percentage_of_visitors=None,
    results=[AnalysisResult(url='https://x', has_keyword=True, mentions_object=True, keyword_found='тест', relevance_score=0.5)],
)
csv = report_to_csv(r)
assert csv.startswith('\ufeff'), 'No BOM'
assert ';' in csv.split('\n')[0], 'No semicolons'
print('CSV PASS')
"
```

- [ ] **Step 4: Verify LLM prompt is clean**

```bash
.\venv\Scripts\python.exe -c "
from app.llm import _build_prompt
p = _build_prompt('obj', ['kw'], 't', 'x')
assert 'has_keyword' not in p
assert 'keyword_found' not in p
assert 'mentions_object' in p
print('PROMPT PASS')
"
```

- [ ] **Step 5: Verify cache key bump**

```bash
.\venv\Scripts\python.exe -c "
from app.analyzer import _cache_keywords
assert _cache_keywords(['a']).endswith('#kwv2')
print('CACHE PASS')
"
```
