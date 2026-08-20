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
