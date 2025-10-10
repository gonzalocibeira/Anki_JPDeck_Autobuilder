"""Helpers to parse monolingual definitions from the Goo Japanese dictionary."""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Iterator, Any

_JSON_LD_RE = re.compile(
    r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)

_HTML_BLOCK_RE = re.compile(
    r"<(?:div|p|li)[^>]*class=['\"][^'\"]*(?:meaning|text|description|content|explanation)[^'\"]*['\"][^>]*>(.*?)</(?:div|p|li)>",
    re.IGNORECASE | re.DOTALL,
)

_META_DESC_RE = re.compile(
    r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"](.*?)['\"]", re.IGNORECASE | re.DOTALL
)


_DICTIONARY_TYPES = {"DefinedTerm", "DictionaryEntry", "Article", "Sense"}


def extract_first_definition_from_json_ld(html: str) -> str:
    """Return the first description entry from Goo's JSON-LD payload, if present."""
    for block in _JSON_LD_RE.findall(html or ""):
        block = block.strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        fallback: str = ""
        for description, priority in _iter_json_descriptions(data):
            cleaned = _clean_text(description)
            if not cleaned:
                continue
            if priority == 0:
                return cleaned
            if not fallback:
                fallback = cleaned
        if fallback:
            return fallback
    return ""


def _iter_json_descriptions(obj: Any) -> Iterator[tuple[str, int]]:
    if isinstance(obj, dict):
        value = obj.get("description")
        if isinstance(value, str):
            typ = obj.get("@type")
            priority = 0 if isinstance(typ, str) and typ in _DICTIONARY_TYPES else 1
            yield value, priority
        for child in obj.values():
            yield from _iter_json_descriptions(child)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_json_descriptions(item)


def extract_first_definition_from_html_blocks(html: str) -> str:
    """Fallback parser: scan definition blocks and strip HTML tags."""
    if not html:
        return ""
    cleaned_html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    for block in _HTML_BLOCK_RE.findall(cleaned_html):
        cleaned = _clean_html_fragment(block)
        if cleaned:
            return cleaned
    meta = _META_DESC_RE.search(cleaned_html)
    if meta:
        return _clean_text(meta.group(1))
    return ""


def extract_first_goo_definition(html: str) -> str:
    """Extract the first Japanese definition from Goo dictionary HTML."""
    if not html:
        return ""
    via_json_ld = extract_first_definition_from_json_ld(html)
    if via_json_ld:
        return via_json_ld
    return extract_first_definition_from_html_blocks(html)


def _clean_html_fragment(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return _clean_text(fragment)


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    # Normalise whitespace but keep intentional newlines
    text = re.sub(r"\r\n?|\r", "\n", text)
    text = re.sub(r"[\t\x0b\f]+", " ", text)
    # Collapse multiple blank lines and spaces
    lines = [line.strip() for line in text.split("\n")]
    # Filter out empty lines but preserve sentence spacing
    filtered = [line for line in lines if line]
    result = " ".join(filtered).strip()
    return result


__all__ = ["extract_first_goo_definition"]
