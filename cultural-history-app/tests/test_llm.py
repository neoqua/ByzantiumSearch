import json
import pytest
from app.llm import _build_prompt, _parse_response, _coerce_result


def test_build_prompt_contains_object_and_keyword():
    prompt = _build_prompt("Test Monastery", ["Byzantium"], "Title", "Some text")
    assert "Test Monastery" in prompt
    assert "Byzantium" in prompt


def test_parse_response_json_object():
    data = {"mentions_object": True, "has_keyword": True, "relevance_score": 0.95}
    result = _parse_response(json.dumps(data))
    assert result["mentions_object"] is True
    assert result["relevance_score"] == 0.95


def test_parse_response_code_block():
    raw = f"```json\n{json.dumps({'mentions_object': False})}\n```"
    result = _parse_response(raw)
    assert result["mentions_object"] is False


def test_parse_response_extra_text():
    raw = f"Here is the result:\n{json.dumps({'has_keyword': True})}\nDone."
    result = _parse_response(raw)
    assert result["has_keyword"] is True


def test_parse_response_raises_on_no_json():
    with pytest.raises(ValueError):
        _parse_response("No JSON here at all")


def test_coerce_result_normalizes_llm_output():
    raw = {
        "mentions_object": "да",
        "has_keyword": "true",
        "keyword_found": "Византия",
        "date_mentioned": None,
        "publication_date": 2025,
        "author_location": "Москва",
        "relevance_score": "высокий",
    }
    result = _coerce_result(raw)
    assert result["mentions_object"] is True
    assert result["has_keyword"] is True
    assert result["keyword_found"] == "Византия"
    assert result["date_mentioned"] is None
    assert result["publication_date"] == "2025"
    assert result["author_location"] == "Москва"
    assert result["relevance_score"] == 0.0


def test_coerce_result_missing_keys_default():
    result = _coerce_result({})
    assert result["mentions_object"] is False
    assert result["has_keyword"] is False
    assert result["relevance_score"] == 0.0
    assert result["keyword_found"] is None
    assert result["publication_date"] is None


def test_coerce_result_keeps_valid_values():
    raw = {
        "mentions_object": True,
        "has_keyword": False,
        "relevance_score": "0,95",
        "keyword_found": "Византия",
    }
    result = _coerce_result(raw)
    assert result["mentions_object"] is True
    assert result["has_keyword"] is False
    assert result["relevance_score"] == 0.95
