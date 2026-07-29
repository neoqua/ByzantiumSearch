import json
import pytest
from app.llm import _build_prompt, _parse_response


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
