import pytest
from app.scraper import extract_text, text_hash


def test_extract_text_removes_tags():
    html = "<html><body><p>Hello <b>world</b></p><script>var x=1;</script></body></html>"
    result = extract_text(html)
    assert "Hello world" in result
    assert "var x" not in result


def test_extract_text_empty():
    assert extract_text("") == ""
    assert extract_text(b"") == ""


def test_extract_text_cp1251_bytes():
    body = "Византия на форуме".encode("cp1251")
    html = (
        b"<html><head><meta http-equiv=\"Content-Type\" "
        b"content=\"text/html; charset=windows-1251\"></head>"
        b"<body><p>" + body + b"</p></body></html>"
    )
    result = extract_text(html)
    assert "Византия" in result
    assert "форуме" in result


def test_text_hash_consistent():
    h1 = text_hash("same text")
    h2 = text_hash("same text")
    assert h1 == h2


def test_text_hash_different():
    h1 = text_hash("text a")
    h2 = text_hash("text b")
    assert h1 != h2
