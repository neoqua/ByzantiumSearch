from app.keyword_match import tokenize, match_keywords, has_keyword, stems_in_order


def test_tokenize_splits_words():
    assert tokenize("Привет мир 123") == ["привет", "мир", "123"]


def test_tokenize_lowercases():
    assert tokenize("Византия") == ["византия"]


def test_single_keyword_morphology():
    text = "Говорим о Византии и её наследии"
    matched, forms = match_keywords(text, ["Византия"])
    assert matched == ["Византия"]
    assert forms == ["византии"]


def test_adjective_form_matches_via_stem_prefix():
    text = "Византийский храм и византиец рядом"
    matched, forms = match_keywords(text, ["Византия"])
    assert matched == ["Византия"]
    assert set(forms) == {"византийский", "византиец"}


def test_short_words_do_not_match_by_reverse_prefix():
    # "в" and "виза" (stem "виз") are prefixes of the keyword stem "визант"
    # but must not count as the keyword.
    text = "В городе нужна виза и визит в консульство"
    assert match_keywords(text, ["Византия"]) == ([], [])


def test_longer_keyword_matches_shorter_page_form():
    text = "Наследие Византии живо"
    matched, forms = match_keywords(text, ["Византийский"])
    assert matched == ["Византийский"]
    assert forms == ["византии"]


def test_single_keyword_no_match():
    text = "Совсем другой текст без ключевых слов"
    assert match_keywords(text, ["Византия"]) == ([], [])


def test_multiple_keywords_or_logic():
    text = "Византия упоминается только один раз в тексте"
    matched, forms = match_keywords(text, ["Византия", "Константинополь"])
    assert matched == ["Византия"]
    assert forms == ["византия"]


def test_multiple_keywords_both_match():
    text = "Византия и Константинополь — это важно"
    matched, forms = match_keywords(text, ["Византия", "Константинополь"])
    assert matched == ["Византия", "Константинополь"]
    assert forms == ["византия", "константинополь"]


def test_has_keyword_true():
    assert has_keyword("Византии", ["Византия"]) is True


def test_has_keyword_false():
    assert has_keyword("Пустой текст", ["Византия"]) is False


def test_phrase_keyword_contiguous():
    text = "Мы посетили Новый Год в этом году"
    matched, forms = match_keywords(text, ["Новый Год"])
    assert matched == ["Новый Год"]
    assert forms == ["новый год"]


def test_phrase_keyword_separated():
    text = "Год был очень новым и интересным"
    assert match_keywords(text, ["Новый Год"]) == ([], [])


def test_latin_keyword():
    text = "The Byzantine Empire was great"
    matched, forms = match_keywords(text, ["Byzantine"])
    assert matched == ["Byzantine"]
    assert forms == ["byzantine"]


def test_empty_keywords():
    assert match_keywords("text", []) == ([], [])


def test_pure_punctuation_keyword():
    assert match_keywords("hello world", ["..."]) == ([], [])


def test_stems_in_order_allows_gaps():
    assert stems_in_order(
        "Свято-Климентовский мужской монастырь",
        "Свято-Климентовский монастырь",
    )
    assert not stems_in_order("Погода в Крыму", "Свято-Климентовский монастырь")
