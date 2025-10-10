from __future__ import annotations

import re

WIKIPEDIA_MAX_CHARS = 260


def clean_wikipedia_extract(extract: str, *, max_chars: int = WIKIPEDIA_MAX_CHARS) -> str:
    text = extract.strip()
    if not text:
        return ""

    normalized = re.sub(r"\s+", " ", text)
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[。！？])\s*", normalized)
        if s.strip()
    ]

    filler_keywords = (
        "曖昧さ回避",
        "この記事",
        "この項目",
        "ウィキペディア",
        "出典を追加",
    )

    def is_filler(sentence: str) -> bool:
        return any(keyword in sentence for keyword in filler_keywords)

    filtered = [s for s in sentences if not is_filler(s)]
    if not filtered and sentences:
        filtered = [sentences[0]]

    cleaned = filtered[0] if filtered else ""
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned
