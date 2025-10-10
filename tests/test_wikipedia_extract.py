from wikipedia_utils import WIKIPEDIA_MAX_CHARS, clean_wikipedia_extract


def test_clean_wikipedia_extract_filters_filler_sentences():
    extract = "この記事では曖昧さ回避について述べています。東京は日本の首都である。"
    assert clean_wikipedia_extract(extract) == "東京は日本の首都である。"


def test_clean_wikipedia_extract_truncates_long_text():
    long_sentence = "太郎" * 200 + "。"
    cleaned = clean_wikipedia_extract(long_sentence)
    assert len(cleaned) <= WIKIPEDIA_MAX_CHARS
    assert cleaned.endswith("…")
