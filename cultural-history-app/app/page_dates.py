import json
import re
from datetime import datetime
from typing import Optional, Union

from bs4 import BeautifulSoup

_ISO_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DOT_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def normalize_date(raw: Optional[str]) -> Optional[str]:
    """Return DD.MM.YYYY or None."""
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    m = _DOT_DATE.match(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%d.%m.%Y")
        except ValueError:
            return None
    iso = text.replace("Z", "+00:00")
    m = _ISO_PREFIX.match(iso)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%d.%m.%Y")
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(iso[:32])
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return None


def _jsonld_dates(node, found: list) -> None:
    if isinstance(node, dict):
        for key in ("datePublished", "dateCreated", "dateModified"):
            val = node.get(key)
            if isinstance(val, str):
                found.append(val)
        for val in node.values():
            _jsonld_dates(val, found)
    elif isinstance(node, list):
        for item in node:
            _jsonld_dates(item, found)


def extract_publication_date(html: Union[str, bytes, None]) -> Optional[str]:
    if html is None:
        return None
    if isinstance(html, bytes) and not html.strip():
        return None
    if isinstance(html, str) and not html.strip():
        return None
    soup = BeautifulSoup(html, "lxml")

    for prop in (
        "article:published_time",
        "og:published_time",
        "article:modified_time",
        "og:updated_time",
    ):
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            parsed = normalize_date(tag["content"])
            if parsed:
                return parsed

    for name in ("publication_date", "date", "pubdate", "sailthru.date"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            parsed = normalize_date(tag["content"])
            if parsed:
                return parsed

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = []
        _jsonld_dates(data, found)
        for item in found:
            parsed = normalize_date(item)
            if parsed:
                return parsed

    tag = soup.find("time", attrs={"datetime": True})
    if tag and tag.get("datetime"):
        parsed = normalize_date(tag["datetime"])
        if parsed:
            return parsed
    return None
