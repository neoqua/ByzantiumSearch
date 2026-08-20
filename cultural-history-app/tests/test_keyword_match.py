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
    text = "Византия упоминается только один раз в тексте"
    result = match_keywords(text, ["Византия", "Константинополь"])
    assert len(result) == 1
    assert result[0] == "Византия"


def test_multiple_keywords_both_match():
    text = "Византия и Константинополь — это важно"
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
