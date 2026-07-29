import json
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


def _build_prompt(object_name: str, keywords: list[str], title: str, text: str) -> str:
    keywords_str = ", ".join(keywords)
    return (
        f'Analyze the text below. Determine if "{object_name}" is mentioned, '
        f'if any of these keywords appear: [{keywords_str}], and extract dates and author location.\n\n'
        f"Object: {object_name}\n"
        f"Keywords: {keywords_str}\n\n"
        f"Title: {title}\n\n"
        f"Text: {text[:3000]}\n\n"
        "Respond in JSON format only:\n"
        '{\n'
        '  "mentions_object": true/false,\n'
        '  "object_name": "name from text or null",\n'
        '  "has_keyword": true/false,\n'
        '  "keyword_found": "which keyword was found or null",\n'
        '  "date_mentioned": "DD.MM.YYYY from text or null",\n'
        '  "publication_date": "DD.MM.YYYY or null",\n'
        '  "author_location": "city, country, region or null",\n'
        '  "relevance_score": 0.0-1.0\n'
        "}"
    )


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
    object_name: str, keywords: list[str], title: str, text: str
) -> dict:
    prompt = _build_prompt(object_name, keywords, title, text)
    payload = {
        "model": settings.lm_studio_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 256,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        url = f"{settings.lm_studio_base_url}/v1/chat/completions"
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_response(content)


async def analyze_text_with_retry(
    object_name: str, keywords: list[str], title: str, text: str, max_retries: int = 2
) -> dict:
    for attempt in range(max_retries + 1):
        try:
            return await analyze_text(object_name, keywords, title, text)
        except Exception as e:
            logger.warning("LLM analysis attempt %d failed: %s", attempt + 1, e)
            if attempt == max_retries:
                return {
                    "mentions_object": False,
                    "has_keyword": False,
                    "keyword_found": None,
                    "date_mentioned": None,
                    "publication_date": None,
                    "author_location": None,
                    "relevance_score": 0.0,
                }
