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


def _stem_matches(page_stem: str, kw_stem: str) -> bool:
    return page_stem.startswith(kw_stem) or kw_stem.startswith(page_stem)


def match_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    tokens = tokenize(text)
    page_stems = [_stem(t) for t in tokens]
    matched_kw = []
    matched_forms = []
    for kw in keywords:
        kw_tokens = tokenize(kw)
        if not kw_tokens:
            continue
        kw_stems = [_stem(t) for t in kw_tokens]
        kw_len = len(kw_stems)
        found_forms = set()
        for i in range(len(page_stems) - kw_len + 1):
            if all(_stem_matches(page_stems[i + j], kw_stems[j]) for j in range(kw_len)):
                start = i
                end = i + kw_len
                form = " ".join(tokens[start:end])
                found_forms.add(form)
        if found_forms:
            matched_kw.append(kw)
            matched_forms.extend(sorted(found_forms))
    return matched_kw, matched_forms


def has_keyword(text: str, keywords: list[str]) -> bool:
    matched_kw, _ = match_keywords(text, keywords)
    return bool(matched_kw)
