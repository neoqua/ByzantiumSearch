import json
import logging
from typing import Optional

from app.llm_providers import get_provider
from app.schemas import LLMSettings

logger = logging.getLogger(__name__)


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


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("да", "true", "yes")
    return False


def _to_float(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def _to_str_or_none(value) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _coerce_result(data: dict) -> dict:
    result = dict(data)
    result["mentions_object"] = _to_bool(result.get("mentions_object"))
    result["has_keyword"] = _to_bool(result.get("has_keyword"))
    result["relevance_score"] = _to_float(result.get("relevance_score"))
    allowed_source_types = {"blog", "forum", "social", "official", "agency", "other"}
    source_type = result.get("source_type")
    if source_type not in allowed_source_types:
        source_type = "other"
    result["source_type"] = source_type
    for key in (
        "keyword_found",
        "date_mentioned",
        "publication_date",
        "author_location",
    ):
        result[key] = _to_str_or_none(result.get(key))
    return result


def _parse_response(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if "```" in text:
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON found in response: {response_text[:200]}")


async def analyze_text(
    object_name: str,
    keywords: list[str],
    title: str,
    text: str,
    llm_settings: Optional[LLMSettings] = None,
) -> dict:
    prompt = _build_prompt(object_name, keywords, title, text)
    provider = get_provider(llm_settings or LLMSettings(provider="local"))
    content = await provider.complete(prompt)
    return _parse_response(content)


async def analyze_text_with_retry(
    object_name: str,
    keywords: list[str],
    title: str,
    text: str,
    max_retries: int = 2,
    llm_settings: Optional[LLMSettings] = None,
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            result = await analyze_text(
                object_name, keywords, title, text, llm_settings=llm_settings
            )
            return _coerce_result(result)
        except Exception as e:
            logger.warning("LLM analysis attempt %d failed: %s", attempt + 1, e)
            if attempt == max_retries:
                return _coerce_result({
                    "mentions_object": False,
                    "has_keyword": False,
                    "keyword_found": None,
                    "date_mentioned": None,
                    "publication_date": None,
                    "author_location": None,
                    "relevance_score": 0.0,
                    "source_type": "other",
                })
