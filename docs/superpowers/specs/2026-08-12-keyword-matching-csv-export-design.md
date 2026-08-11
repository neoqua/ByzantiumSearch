# Spec: Morphology-aware keyword matching + CSV export

**Date:** 2026-08-12
**Status:** Approved (user chose variant A for matching; CSV `;` delimiter + all table columns)
**Base:** current `master` (`008198e`)

## Problem

Functional testing revealed three issues:

1. **Keyword matching ignores word formation.** The keyword is judged by the LLM only.
   E.g. keyword «Византия» does not match «Византии», «Византийский» on the page, so the
   page is reported as having no keywords even though a word-form of the keyword is present.
2. **Multiple keywords are treated as AND.** Several comma-separated keywords are only
   counted when **all** of them are present, and only one found-keyword value is recorded.
   Required: at least **one** keyword from the list should match, and every matched keyword
   must be recorded.
3. **No export.** The results page has only a «Новый анализ» link; there is no way to save
   the report to an external file.

Root cause of 1+2: `has_keyword` / `keyword_found` are produced by the LLM
(`app/llm.py` prompt), which is non-deterministic and morphology-unreliable.

## Design decisions (from brainstorming)

| Question | Decision |
|---|---|
| Matching mechanism | **Variant A — local deterministic stem matching** (`snowballstemmer`, pure-Python, Russian + English stemmers). LLM no longer decides `has_keyword`/`keyword_found`; it keeps mentions_object, dates, geolocation, relevance, source_type |
| Word formation | Compare word **stems**: «Византия» matches «Византии», «Византийский», «византиец» (any form sharing the stem) |
| Phrase keywords | A multi-word keyword matches when its stemmed words appear in the page's stemmed token stream **contiguously and in order** |
| Multiple keywords | `has_keyword=True` if **at least one** keyword matches; `keyword_found` = comma-joined list of **all** matched keywords (original form) |
| `keyword_found` type | stays `Optional[str]` (comma-joined for several matches) — no DB migration |
| CSV | Server-side endpoint `GET /results/{task_id}/csv`; `;` delimiter; UTF-8 **with BOM** (opens correctly in Russian Excel); columns №, URL, Заголовок, Источник, Ключевые слова, Дата, Геопривязка, Релевантность, Упоминает объект (да/нет) |
| Export link | «Сохранить в CSV» next to «Новый анализ» in `results.html` |
| Stale URL-cache rows | Bump the cache-key format so previously cached LLM-judged entries are not reused |

## Keyword matching module (`app/keyword_match.py`)

New module with pure functions only (no I/O, fully testable):

- `tokenize(text) -> list[str]` — lowercase words matching `[а-яёa-z0-9]+`.
- `_stem(token) -> str` — `snowballstemmer` Russian stemmer for Cyrillic tokens,
  English stemmer for Latin tokens; non-alphabetic tokens returned lowercased as-is.
- `match_keywords(text, keywords: list[str]) -> list[str]` — for each keyword:
  tokenize + stem it; the keyword is matched iff its stemmed tokens form a **contiguous
  subsequence (in order)** of the page's stemmed token stream. Single-word keywords are
  just token membership. Returns matched keywords in their original form. Keywords that
  tokenize to nothing (e.g. pure punctuation) never match.
- `has_keyword(text, keywords) -> bool` — `bool(match_keywords(...))`.

Dependency: `snowballstemmer>=2.2` added to `requirements.txt` (and installed in venv).

## Pipeline integration (`app/scraper.py`)

In `fetch_and_analyze`, after `text = await fetch_page_text(url)` (and before returning
the early error dict):

- `matched = match_keywords(text, keywords)`
- set `has_keyword=bool(matched)`, `keyword_found=", ".join(matched) or None`
  on the result dict.

These two fields become authoritatively local; they are stored in the URL-cache
`result_json` like today, so both fresh and cached paths carry correct values.
No-text path already returns `has_keyword=False`, `keyword_found=None` — unchanged.

## LLM prompt (`app/llm.py`)

- Remove `has_keyword` and `keyword_found` from the prompt's JSON contract — the LLM
  must not judge them anymore.
- The keyword list stays in the prompt text (still needed for relevance judgment).
- `_coerce_result` keeps tolerating their absence (defaults `False` / `None`); the local
  override in `fetch_and_analyze` sets the real values afterwards.

## Cache key version bump (`app/analyzer.py`)

- `_cache_keywords(keywords)` currently returns `",".join(keywords)`. Change the format
  to include a marker, e.g. `",".join(keywords) + "#kwv2"`, so rows cached before this
  feature (LLM-judged keyword fields) are treated as stale and recomputed. No schema
  change; the marker is only part of the cache key comparison.

## CSV export

### Serializer (pure function, `app/report.py`)

`report_to_csv(report: ReportData) -> str`:

- `csv.writer` over `io.StringIO`, `delimiter=";"`, `lineterminator="\r\n"`.
- Header: `№; URL; Заголовок; Источник; Ключевые слова; Дата; Геопривязка; Релевантность; Упоминает объект`.
- Per result row:
  - `№` — 1-based index
  - `Дата` — `publication_date or date_mentioned or ""`
  - `Упоминает объект` — `да` / `нет`
  - others mirror the results table columns directly.
- Empty results → header row only.
- Return the string with a leading `\ufeff` (BOM).

### Endpoint (`app/main.py`)

`GET /results/{task_id}/csv`:

- `report = await build_report(task_id, db)`; `404 {"error": "not found"}` if `None`.
- `csv_bytes = report_to_csv(report).encode("utf-8")`.
- `Response(csv_bytes, media_type="text/csv; charset=utf-8",
  headers={"Content-Disposition": 'attachment; filename="report_{task_id}.csv"'})`.

### Frontend (`app/templates/results.html`)

- Next to «Новый анализ» (results.html:77) add
  `<a href="/results/{{ report.task_id }}/csv" download>Сохранить в CSV</a>`.

## Files touched

- Create: `app/keyword_match.py`, `tests/test_keyword_match.py`
- Modify: `app/scraper.py`, `app/llm.py`, `app/analyzer.py` (cache key),
  `app/report.py` (`report_to_csv`), `app/main.py` (CSV endpoint),
  `app/templates/results.html`, `requirements.txt`, `AGENTS.md` (architecture note),
  `tests/test_llm.py` (prompt contract), `tests/test_api.py` (CSV endpoint test)

## Testing / verification

pytest files written "for the record" (pytest hangs on this dev machine per AGENTS.md);
verify with venv `python -c` and throwaway monkeypatch scripts:

- `tests/test_keyword_match.py` (pure, run via `python -c`):
  - «Византия» matches «Византии» / «Византийский» / «византиец» (issue 1).
  - Several keywords: page matching only one → `has_keyword=True`,
    `keyword_found` lists that one; page matching two → both recorded (issue 2).
  - Phrase keyword: matched when contiguous and in order; not matched when the words are
    separated or one is missing.
  - Latin keyword matching.
- `tests/test_api.py`: `GET /results/{task_id}/csv` with a seeded `Result` row — assert
  200, `text/csv` content type, `Content-Disposition` filename, BOM present, `;`
  delimiter, header columns, «да/нет» in the object-mention column; 404 for unknown task.
- `tests/test_llm.py`: assert the prompt no longer contains `has_keyword` /
  `keyword_found` in the JSON contract; `_coerce_result` tests unchanged.
- Integration: throwaway script monkeypatching `app.scraper.fetch_page_text` to return
  text containing «византии» and `analyze_text_with_retry` to a canned dict; assert
  `fetch_and_analyze` returns `has_keyword=True` / `keyword_found="Византия"`.
- Cache check: `_cache_keywords(["a","b"])` differs from the old format.

## Out of scope

- Synonym matching / fuzzy matching (only word-form matching per user decision).
- Changing `keyword_found` to a structured list type in the API (comma-joined string per
  decision).
- Client-side CSV generation (server endpoint chosen).
- Transliteration / handling of mixed-script tokens beyond per-token stemmer selection.
