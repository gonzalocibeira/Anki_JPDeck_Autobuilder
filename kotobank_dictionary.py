"""Helpers to parse monolingual definitions from the Kotobank Japanese dictionary."""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Iterator

_JSON_LD_RE = re.compile(
    r"<script[^>]+type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

_HTML_BLOCK_RE = re.compile(
    r"<(?:section|div|p|dd|li)[^>]*(?:class|itemprop)=['\"][^'\">]*(?:meaning|description|content|text|kiji|entry|body|def|definition)['\"][^>]*>(.*?)</(?:section|div|p|dd|li)>",
    re.IGNORECASE | re.DOTALL,
)

_META_DESC_RE = re.compile(
    r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"](.*?)['\"]",
    re.IGNORECASE | re.DOTALL,
)

_DICTIONARY_TYPES = {"DefinedTerm", "DictionaryEntry", "Article", "Sense"}

_NOISE_SNIPPETS = (
    "サービス終了のお知らせ",
    "Kotobank（コトバンク）は",
    "コトバンクは",
    "kotobank.jp",
)


def extract_first_kotobank_definition(html: str) -> str:
    """Extract the first Japanese definition from Kotobank dictionary HTML."""
    if not html:
        return ""

    via_json_ld = _extract_first_definition_from_json_ld(html)
    if via_json_ld:
        return via_json_ld
    return _extract_first_definition_from_html_blocks(html)


def _extract_first_definition_from_json_ld(html: str) -> str:
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
            if not cleaned or _is_noise_definition(cleaned):
                continue
            if priority == 0:
                return cleaned
            if not fallback:
                fallback = cleaned
        if fallback and not _is_noise_definition(fallback):
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


def _extract_first_definition_from_html_blocks(html: str) -> str:
    cleaned_html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    for block in _HTML_BLOCK_RE.findall(cleaned_html):
        cleaned = _clean_html_fragment(block)
        if cleaned and not _is_noise_definition(cleaned):
            return cleaned
    meta = _META_DESC_RE.search(cleaned_html)
    if meta:
        cleaned_meta = _clean_text(meta.group(1))
        if cleaned_meta and not _is_noise_definition(cleaned_meta):
            return cleaned_meta
    return ""


def _clean_html_fragment(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"</?(?:rt|rp)>", "", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return _clean_text(fragment)


def _clean_text(text: str) -> str:
    text = unescape(text or "")
    text = re.sub(r"\r\n?|\r", "\n", text)
    text = re.sub(r"[\t\x0b\f]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    filtered = [line for line in lines if line]
    return " ".join(filtered).strip()


def _is_noise_definition(text: str) -> bool:
    if not text:
        return True
    for snippet in _NOISE_SNIPPETS:
        if snippet in text:
            return True
    return False


__all__ = ["extract_first_kotobank_definition"]
