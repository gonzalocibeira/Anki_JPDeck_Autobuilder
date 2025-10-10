from __future__ import annotations
"""Utilities for parsing Japanese definitions from Wiktionary extracts."""

import re
from typing import Final

__all__ = ["extract_first_japanese_definition"]

WIKTIONARY_HEADING_STOP_WORDS: Final = {
    "語源",
    "熟語",
    "派生語",
    "関連語",
    "翻訳",
    "脚注",
    "参照",
    "諸言語",
}

WIKTIONARY_PART_OF_SPEECH_MARKERS: Final = {
    "名詞",
    "動詞",
    "形容詞",
    "形容動詞",
    "副詞",
    "助詞",
    "助動詞",
    "連体詞",
    "感動詞",
    "接続詞",
    "接頭辞",
    "接尾辞",
    "形容詞語幹",
    "固有名詞",
}

_SECTION_RE = re.compile(r"^=+\s*日本語\s*=+$")
_NUMBER_PREFIX_RE = re.compile(r"^(?:\d+|[①-⑳]|[０-９]+)[.．、)）]?\s*")
_BULLET_PREFIX_RE = re.compile(r"^[#・◆▶▷►＊※●○]\s*")


def _clean_line(line: str) -> str:
    cleaned = _NUMBER_PREFIX_RE.sub("", line)
    cleaned = _BULLET_PREFIX_RE.sub("", cleaned)
    return cleaned.strip()


def extract_first_japanese_definition(extract: str) -> str:
    """Return the first usable JP definition line from a Wiktionary extract."""

    lines = [line.strip() for line in extract.splitlines() if line.strip()]
    in_japanese_section = False

    for line in lines:
        normalized = line.rstrip("：:")
        heading_text = normalized.strip("=")
        is_heading = heading_text != normalized
        token = heading_text if is_heading else normalized
        token = token.strip()

        if not in_japanese_section:
            if token == "日本語":
                in_japanese_section = True
            continue

        if token == "":
            continue

        if token in WIKTIONARY_PART_OF_SPEECH_MARKERS:
            continue

        if token in WIKTIONARY_HEADING_STOP_WORDS or (
            token.endswith("語") and len(token) <= 4
        ):
            break

        if is_heading and token != "日本語":
            break

        cleaned = _clean_line(token)
        if cleaned:
            return cleaned

    sentences = re.split(r"(?<=。)", extract)
    return sentences[0].strip() if sentences else extract.strip()
