#!/usr/bin/env python3
"""
Anki Deck Builder (MVP)
-----------------------
Builds an Anki .apkg deck from a CSV (single column of Japanese terms).
- Friendly terminal UI (Typer + Rich)
- New deck OR append-to-existing (by reusing deck/model IDs so importing merges in Anki)
- Fetches:
  * Kana reading + EN glosses: Jisho API
  * Example sentence (JP) + EN translation: Tatoeba API
  * JP monolingual definition: Japanese Wikipedia (fallback: Wiktionary → Kotobank 国語辞典)
  * Related image: DuckDuckGo image search thumbnail

Requires: pip install typer[all] rich requests genanki unidecode python-slugify
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple
from urllib.parse import quote

try:
    import requests  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled gracefully for optional deps
    requests = None  # type: ignore

try:
    from gtts import gTTS  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled gracefully for optional deps
    gTTS = None  # type: ignore
import typer
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from slugify import slugify
import genanki
from unidecode import unidecode

from kotobank_dictionary import extract_first_kotobank_definition
from wikipedia_utils import clean_wikipedia_extract
from wiktionary_parser import extract_first_japanese_definition

app = typer.Typer(add_completion=False)
console = Console(record=True)

# -----------------------------
# Config / Constants
# -----------------------------
USER_AGENT = "AnkiDeckBuilder/1.0 (+https://github.com/)"
HEADERS = {"User-Agent": USER_AGENT}

JISHO_URL = "https://jisho.org/api/v1/search/words"
TATOEBA_URL = "https://tatoeba.org/eng/api_v0/search"
KOTOBANK_ENTRY_URL = "https://kotobank.jp/word/{term}"
KOTOBANK_SEARCH_URL = "https://kotobank.jp/s/{term}"
WIKIPEDIA_JA_API = "https://ja.wikipedia.org/w/api.php"
WIKTIONARY_JA_API = "https://ja.wiktionary.org/w/api.php"
DUCKDUCKGO_BASE = "https://duckduckgo.com/"

DEFAULT_MODEL_NAME = "JP Word w/ Image + Examples (MVP)"
DEFAULT_GRAMMAR_MODEL_NAME = "JP Grammar Concept (MVP)"
DEFAULT_DECK_NAME = "Japanese Auto Deck"
CONFIG_FILE = "anki_deck_builder.config.json"
MEDIA_DIR_NAME = "media"

# -----------------------------
# Data structures
# -----------------------------
@dataclass
class CardData:
    term: str
    reading: str = ""
    english: str = ""
    sentence_jp: str = ""
    sentence_en: str = ""
    definition_ja: str = ""
    image_filename: str = ""  # local filename (downloaded)
    audio_filename: str = ""  # local filename (generated)
    sentence_audio_filename: str = ""  # local filename (generated)

    def to_fields(self) -> List[str]:
        # Order must match the model fields list below
        img_tag = f'<img src="{self.image_filename}" />' if self.image_filename else ''
        audio_tag = f"[sound:{self.audio_filename}]" if self.audio_filename else ""
        sentence_audio_tag = (
            f"[sound:{self.sentence_audio_filename}]" if self.sentence_audio_filename else ""
        )
        return [
            self.term,
            self.reading,
            self.english,
            self.sentence_jp,
            self.sentence_en,
            sentence_audio_tag,
            self.definition_ja,
            audio_tag,
            f"<div>{img_tag}</div>",
        ]


@dataclass
class GrammarCardData:
    question: str
    explanation: str = ""
    example_jp: str = ""
    example_en: str = ""
    example_audio_filename: str = ""

    def to_fields(self) -> List[str]:
        audio_tag = (
            f"[sound:{self.example_audio_filename}]" if self.example_audio_filename else ""
        )
        return [
            self.question,
            self.explanation,
            self.example_jp,
            audio_tag,
            self.example_en,
        ]


# -----------------------------
# Build orchestration types
# -----------------------------


class BuildError(RuntimeError):
    """Raised when the build process cannot complete."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class InputMode(str, Enum):
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"


@dataclass
class BuildParams:
    csv_path: Path
    output_dir: Path
    new_deck: bool
    deck_name: str = DEFAULT_DECK_NAME
    config_path: Optional[Path] = None
    debug: bool = False
    mode: InputMode = InputMode.VOCABULARY


@dataclass
class BuildResult:
    deck_name: str
    deck_id: int
    model_id: int
    apkg_path: Path
    config_path: Path
    total_terms: int
    notes_added: int
    media_files: List[str]
    mode: InputMode


class BuildReporter(Protocol):
    def info(self, message: str) -> None:
        ...

    def warning(self, message: str) -> None:
        ...

    def error(self, message: str) -> None:
        ...

    def debug(self, message: str) -> None:
        ...

    def progress_start(self, total: int, description: str = "") -> None:
        ...

    def progress_advance(self, advance: int = 1) -> None:
        ...

    def progress_finish(self) -> None:
        ...


class NullBuildReporter:
    """Default reporter that swallows all events."""

    def info(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        return None

    def error(self, message: str) -> None:
        return None

    def debug(self, message: str) -> None:
        return None

    def progress_start(self, total: int, description: str = "") -> None:
        return None

    def progress_advance(self, advance: int = 1) -> None:
        return None

    def progress_finish(self) -> None:
        return None


class RichBuildReporter(NullBuildReporter):
    """Reporter implementation that proxies events to a Rich console."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self._progress: Optional[Progress] = None
        self._task_id: Optional[int] = None

    def info(self, message: str) -> None:
        self.console.print(f"[green]{message}[/]")

    def warning(self, message: str) -> None:
        self.console.print(f"[yellow]{message}[/]")

    def error(self, message: str) -> None:
        self.console.print(f"[red]{message}[/]")

    def debug(self, message: str) -> None:
        self.console.log(f"[magenta]DEBUG {message}")

    def progress_start(self, total: int, description: str = "") -> None:
        if self._progress is not None:
            return
        description = description or "Working..."
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )
        self._progress.__enter__()
        self._task_id = self._progress.add_task(description, total=total)

    def progress_advance(self, advance: int = 1) -> None:
        if self._progress is None or self._task_id is None:
            return
        self._progress.advance(self._task_id, advance)

    def progress_finish(self) -> None:
        if self._progress is None:
            return
        progress = self._progress
        self._progress = None
        self._task_id = None
        progress.__exit__(None, None, None)

# -----------------------------
# Helpers
# -----------------------------

def read_csv_single_column(path: Path) -> List[str]:
    """Read a CSV (any common delimiter) and return the first non-empty cell per row.
    Also tolerates single-column files with stray semicolons.
    """
    words: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        # Try to sniff delimiter; fallback to regex split on ; , or TAB
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample)
            reader = csv.reader(f, dialect)
            for row in reader:
                if not row:
                    continue
                # pick first non-empty trimmed token
                cell = next((c.strip() for c in row if c and c.strip()), "")
                if cell:
                    words.append(cell)
        except Exception:
            # Fallback: manual split
            for line in f:
                line = line.strip()
                if not line:
                    continue
                tokens = [t.strip() for t in re.split(r"[;,	]", line) if t.strip()]
                if tokens:
                    words.append(tokens[0])
    return words


def read_grammar_csv(path: Path) -> List[GrammarCardData]:
    """Parse a grammar CSV with question/explanation/example columns."""

    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z]", "", value.lower())

    required = ["question", "explanation", "example_jp", "example_en"]
    normalized_lookup = {_normalize(key): key for key in required}

    entries: List[GrammarCardData] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)

        mapping: Optional[Dict[str, int]] = None
        for row in reader:
            cells = [cell.strip() for cell in row]
            if not any(cells):
                continue

            if mapping is None:
                normalized = [_normalize(cell) for cell in cells]
                header_matches = {
                    normalized_lookup[val]: idx
                    for idx, val in enumerate(normalized)
                    if val in normalized_lookup
                }
                if len(header_matches) == len(required):
                    mapping = header_matches
                    continue
                mapping = {key: idx for idx, key in enumerate(required)}

            values: Dict[str, str] = {}
            for key in required:
                idx = mapping.get(key)
                value = cells[idx] if idx is not None and idx < len(cells) else ""
                values[key] = value

            if not values["question"]:
                # Anki requires the first field to have content; skip invalid rows
                continue

            entries.append(
                GrammarCardData(
                    question=values["question"],
                    explanation=values["explanation"],
                    example_jp=values["example_jp"],
                    example_en=values["example_en"],
                )
            )

    return entries


def safe_filename(base: str) -> str:
    s = slugify(base, lowercase=False, separator="_")
    return s or hashlib.md5(base.encode("utf-8")).hexdigest()[:10]


def deterministic_guid(*parts: str) -> int:
    h = hashlib.md5("::".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)  # genanki Note/Deck IDs are 32-bit ints OK


# -----------------------------
# Fetchers (no-auth public sources)
# -----------------------------

def _debug_print(
    source: str,
    term: str,
    payload: Any,
    *,
    limit: int = 600,
    logger: Optional[Callable[[str], None]] = None,
) -> None:
    """Render a concise, human-readable snippet for debug output."""
    try:
        if isinstance(payload, str):
            normalized = re.sub(r"\s+", " ", payload).strip()
        else:
            normalized = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception:
        normalized = str(payload)

    if len(normalized) > limit:
        normalized = normalized[: limit - 1].rstrip() + "…"

    message = f"DEBUG {source} response for '{term}': {normalized}"
    if logger is not None:
        logger(message)
    else:
        console.log(f"[cyan]{message}")


def _require_requests() -> None:
    if requests is None:  # pragma: no cover - triggered only when dependency missing
        raise RuntimeError(
            "The 'requests' package is required for network operations. Install it via 'pip install requests'."
        )


def _require_gtts() -> None:
    if gTTS is None:  # pragma: no cover - triggered only when dependency missing
        raise RuntimeError(
            "The 'gTTS' package is required for audio synthesis. Install it via 'pip install gTTS'."
        )


_gtts_missing_warned = False


def generate_term_audio(term: str, reading: str, media_dir: Path) -> str:
    global _gtts_missing_warned
    candidates = []
    if term and term.strip():
        candidates.append(term.strip())
    if reading and reading.strip() and reading.strip() not in candidates:
        candidates.append(reading.strip())

    if not candidates:
        return ""

    try:
        _require_gtts()
    except RuntimeError as exc:
        if not _gtts_missing_warned:
            message = str(exc)
            if hasattr(console, "print"):
                console.print(f"[red]{message}")
            else:  # pragma: no cover - exercised in tests with dummy console
                console.log(message)
            _gtts_missing_warned = True
        return ""

    filename_seed = candidates[0]
    filename = safe_filename(f"{filename_seed}_audio") + ".mp3"
    dest = media_dir / filename

    for idx, text in enumerate(candidates):
        try:
            tts = gTTS(text=text, lang="ja")  # type: ignore[misc]
            tts.save(str(dest))
            return filename
        except Exception as e:  # pragma: no cover - network or library specific failures
            if dest.exists():
                dest.unlink()
            console.log(f"[yellow]gTTS synthesis failed for '{text}': {e}")
            if idx == len(candidates) - 1:
                return ""
    return ""


def generate_sentence_audio(sentence: str, media_dir: Path) -> str:
    global _gtts_missing_warned
    if not sentence or not sentence.strip():
        return ""

    try:
        _require_gtts()
    except RuntimeError as exc:
        if not _gtts_missing_warned:
            message = str(exc)
            if hasattr(console, "print"):
                console.print(f"[red]{message}")
            else:  # pragma: no cover - exercised in tests with dummy console
                console.log(message)
            _gtts_missing_warned = True
        return ""

    text = sentence.strip()
    base = text[:30]
    hash_suffix = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    filename = safe_filename(f"{base}_{hash_suffix}_sentence_audio") + ".mp3"
    dest = media_dir / filename

    try:
        tts = gTTS(text=text, lang="ja")  # type: ignore[misc]
        tts.save(str(dest))
        return filename
    except Exception as e:  # pragma: no cover - network or library specific failures
        if dest.exists():
            dest.unlink()
        console.log(f"[yellow]gTTS synthesis failed for sentence '{text}': {e}")
        return ""


def fetch_jisho(
    term: str,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str]:
    """Return (reading_kana, english_glosses) from Jisho for a term."""
    _require_requests()
    try:
        resp = requests.get(JISHO_URL, params={"keyword": term}, headers=HEADERS, timeout=15)
        if debug and logger is not None:
            logger(f"DEBUG raw Jisho response for '{term}': {resp.text}")
        elif debug:
            console.log(
                f"[cyan]DEBUG Jisho response for '{term}':[/] {resp.text}"
            )
        resp.raise_for_status()
        data = resp.json()
        if debug:
            first_entry = (data.get("data") or [{}])[0] if data.get("data") else {}
            summary = {
                "meta": data.get("meta", {}),
                "first_japanese": first_entry.get("japanese", []),
                "first_sense": {},
            }
            senses = first_entry.get("senses", []) if isinstance(first_entry, dict) else []
            if senses:
                first_sense = senses[0] if isinstance(senses[0], dict) else {}
                summary["first_sense"] = {
                    "parts_of_speech": first_sense.get("parts_of_speech", []),
                    "english_definitions": first_sense.get("english_definitions", []),
                    "tags": first_sense.get("tags", []),
                }
            _debug_print("Jisho", term, summary, logger=logger)
        if not data.get("data"):
            return "", ""
        first = data["data"][0]
        reading = (first.get("japanese", [{}])[0] or {}).get("reading", "")
        # Combine first sense's english_definitions (fallback to joining all senses)
        senses = first.get("senses", [])
        if senses:
            defs_primary = senses[0].get("english_definitions", [])
            if defs_primary:
                english = "; ".join(defs_primary)
            else:
                english = "; ".join(
                    [", ".join(s.get("english_definitions", [])) for s in senses if s.get("english_definitions")]
                )
        else:
            english = ""
        return reading or "", english or ""
    except Exception as e:
        console.log(f"[yellow]Jisho fetch failed for '{term}': {e}")
        return "", ""


def fetch_tatoeba_example(
    term: str,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str]:
    """Return (jp_sentence, en_translation) from Tatoeba.
    Handles API shapes where 'translations' may be a list of dicts or grouped lists.
    Prefers results marked as "native" and chooses the longest available sentence.
    """
    _require_requests()

    def _collect_candidates(payload: Dict[str, Any], *, native: bool) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        results = payload.get("results", [])
        if not isinstance(results, list):
            return candidates

        for res in results:
            if not isinstance(res, dict):
                continue
            jp_text = (res.get("text") or "").strip()
            if not jp_text:
                continue
            translations = res.get("translations")
            english_texts: List[str] = []

            if isinstance(translations, list):
                flat: List[Dict[str, Any]] = []
                for item in translations:
                    if isinstance(item, dict):
                        flat.append(item)
                    elif isinstance(item, list):
                        flat.extend([sub for sub in item if isinstance(sub, dict)])
                for trans in flat:
                    if trans.get("lang") in ("eng", "en"):
                        text = (trans.get("text") or "").strip()
                        if text:
                            english_texts.append(text)
            elif isinstance(translations, dict):
                for key in ("eng", "en"):
                    items = translations.get(key)
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if isinstance(item, dict):
                            text = (item.get("text") or "").strip()
                            if text:
                                english_texts.append(text)

            if not english_texts:
                continue

            jp_length = len(re.sub(r"\s+", "", jp_text))
            for en_text in english_texts:
                candidates.append(
                    {
                        "jp": jp_text,
                        "en": en_text,
                        "length": jp_length,
                        "native": native,
                    }
                )
        return candidates

    def _perform_request(extra_params: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        params = {
            "from": "jpn",
            "query": term,
            "to": "eng",
            "trans_filter": "limit",
            "trans_link": "direct",
            "trans_to": "eng",
        }
        params.update(extra_params)
        response = requests.get(TATOEBA_URL, params=params, headers=HEADERS, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            payload = {}

        if debug:
            sample_result: Dict[str, Any] = {}
            results = payload.get("results", [])
            if isinstance(results, list) and results:
                first = results[0]
                if isinstance(first, dict):
                    translations_preview: List[Dict[str, Any]] = []
                    translations = first.get("translations")
                    if isinstance(translations, list):
                        for item in translations:
                            if isinstance(item, dict):
                                translations_preview.append(
                                    {"lang": item.get("lang"), "text": item.get("text", "")}
                                )
                            elif isinstance(item, list):
                                for sub in item:
                                    if isinstance(sub, dict):
                                        translations_preview.append(
                                            {"lang": sub.get("lang"), "text": sub.get("text", "")}
                                        )
                            if len(translations_preview) >= 2:
                                break
                    elif isinstance(translations, dict):
                        for lang, items in list(translations.items())[:2]:
                            if isinstance(items, list) and items:
                                first_item = items[0]
                                if isinstance(first_item, dict):
                                    translations_preview.append(
                                        {"lang": lang, "text": first_item.get("text", "")}
                                    )
                    sample_result = {
                        "text": first.get("text", ""),
                        "lang": first.get("lang"),
                        "translations_preview": translations_preview,
                    }
            summary = {
                "params": extra_params,
                "total": len(results) if isinstance(results, list) else 0,
                "sample": sample_result,
            }
            _debug_print("Tatoeba", term, summary, logger=logger)

        candidates = _collect_candidates(payload, native=bool(extra_params.get("native")))
        return payload, candidates

    try:
        _, native_candidates = _perform_request({"native": "yes"})
        all_candidates = list(native_candidates)

        if not all_candidates:
            _, fallback_candidates = _perform_request({})
            all_candidates.extend(fallback_candidates)

        if not all_candidates:
            return "", ""

        preferred = [c for c in all_candidates if c.get("native")]
        search_pool = preferred if preferred else all_candidates
        best = max(search_pool, key=lambda c: c.get("length", 0))
        if best.get("length", 0) > 20:
            short_candidates = [c for c in search_pool if c.get("length", 0) <= 20]
            if short_candidates:
                best = max(short_candidates, key=lambda c: c.get("length", 0))
        return best.get("jp", ""), best.get("en", "")
    except Exception as e:
        console.log(f"[yellow]Tatoeba fetch failed for '{term}': {e}")
        return "", ""


def fetch_kotobank_ja_definition(
    term: str,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> str:
    """Return a short JP definition from Kotobank's 国語辞典."""
    _require_requests()
    encoded = quote(term, safe="")
    for url_template in (KOTOBANK_ENTRY_URL, KOTOBANK_SEARCH_URL):
        url = url_template.format(term=encoded)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            if debug:
                _debug_print("Kotobank", term, f"URL: {url}\n{resp.text}", logger=logger)
        except Exception as e:
            console.log(f"[yellow]Kotobank fetch failed for '{term}' at {url}: {e}")
            continue

        definition = extract_first_kotobank_definition(resp.text)
        if definition:
            return definition[:400]
    return ""


def fetch_wiktionary_ja_definition(
    term: str,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> str:
    """Return the first Japanese definition from Japanese Wiktionary."""
    _require_requests()
    try:
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": 1,
            "titles": term,
            "redirects": 1,
        }
        r = requests.get(WIKTIONARY_JA_API, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        j = r.json()
        pages = (j.get("query", {}) or {}).get("pages", {})
        if debug:
            first_page: Dict[str, Any] = {}
            if isinstance(pages, dict) and pages:
                first_page = next(iter(pages.values())) or {}
            summary = {
                "pageid": first_page.get("pageid"),
                "title": first_page.get("title"),
                "extract_preview": (first_page.get("extract", "") or "")[:400],
            }
            _debug_print("Wiktionary JA", term, summary, logger=logger)
        if not pages:
            return ""
        page = next(iter(pages.values())) or {}
        extract = page.get("extract") or ""
        if not extract:
            return ""
        return extract_first_japanese_definition(extract)
    except Exception as e:
        console.log(f"[yellow]Wiktionary JA fetch failed for '{term}': {e}")
        return ""


def fetch_wikipedia_ja_definition(
    term: str,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> str:
    """Return a short JP extract from Japanese Wikipedia (if any)."""
    _require_requests()
    try:
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "titles": term,
            "redirects": 1,
        }
        r = requests.get(WIKIPEDIA_JA_API, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        if debug and logger is not None:
            logger(f"DEBUG raw Wikipedia JA response for '{term}': {r.text}")
        elif debug:
            console.log(
                f"[cyan]DEBUG Wikipedia JA response for '{term}':[/] {r.text}"
            )
        j = r.json()
        if debug:
            pages = (j.get("query", {}) or {}).get("pages", {})
            first_page: Dict[str, Any] = {}
            if isinstance(pages, dict) and pages:
                first_page = next(iter(pages.values())) or {}
            summary = {
                "pageid": first_page.get("pageid"),
                "title": first_page.get("title"),
                "extract_preview": (first_page.get("extract", "") or "")[:400],
            }
            _debug_print("Wikipedia JA", term, summary, logger=logger)
        pages = (j.get("query", {}) or {}).get("pages", {})
        if not pages:
            return ""
        page = next(iter(pages.values()))
        extract = (page or {}).get("extract", "")
        if extract:
            return clean_wikipedia_extract(extract)
        return ""
    except Exception as e:
        console.log(f"[yellow]Wikipedia JA fetch failed for '{term}': {e}")
        return ""


def fetch_duckduckgo_image(term: str, media_dir: Path) -> str:
    """Download first DuckDuckGo image search result. Return local filename or ''."""
    _require_requests()
    try:
        search_resp = requests.get(
            DUCKDUCKGO_BASE,
            params={"q": term, "iax": "images", "ia": "images"},
            headers=HEADERS,
            timeout=20,
        )
        search_resp.raise_for_status()
        match = re.search(r"vqd=['\"]?([\w-]+)['\"]?", search_resp.text)
        if not match:
            return ""
        vqd = match.group(1)

        params = {
            "l": "us-en",
            "o": "json",
            "q": term,
            "vqd": vqd,
            "f": ",,,",
            "p": "1",
        }
        headers = {**HEADERS, "Referer": DUCKDUCKGO_BASE}
        r = requests.get(
            f"{DUCKDUCKGO_BASE}i.js",
            params=params,
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            return ""
        url = results[0].get("image") or results[0].get("thumbnail")
        if not url:
            return ""

        suffix = os.path.splitext(url.split("?")[0])[1]
        if not suffix:
            suffix = ".jpg"
        fn = safe_filename(f"{term}_img") + suffix
        dest = media_dir / fn
        with requests.get(url, headers=headers, timeout=30, stream=True) as img:
            img.raise_for_status()
            with open(dest, "wb") as out:
                for chunk in img.iter_content(chunk_size=65536):
                    if chunk:
                        out.write(chunk)
        return fn
    except Exception as e:
        console.log(f"[yellow]DuckDuckGo image fetch failed for '{term}': {e}")
        return ""


# -----------------------------
# Anki model/deck helpers
# -----------------------------

def build_model(model_id: int, name: str = DEFAULT_MODEL_NAME) -> genanki.Model:
    css = """
    .jp { font-family: 'Hiragino Kaku Gothic Pro', 'Meiryo', 'Noto Sans JP', sans-serif; font-size: 28px; }
    .reading { color: #555; font-size: 20px; }
    .en { margin-top: 8px; font-size: 16px; }
    .def { margin-top: 8px; font-size: 16px; color: #333; }
    .ex { margin-top: 10px; }
    .audio { margin-top: 10px; }
    img { max-width: 50%; height: auto; }
    .front { text-align: center; }
    .back { text-align: left; }
    """
    fields = [
        {"name": "Expression"},
        {"name": "Reading"},
        {"name": "English"},
        {"name": "SentenceJP"},
        {"name": "SentenceEN"},
        {"name": "SentenceAudio"},
        {"name": "DefinitionJP"},
        {"name": "Audio"},
        {"name": "Image"},
    ]
    templates = [
        {
            "name": "Card 1",
            "qfmt": """\
<div class='front'>
  <div class='jp'>{{Expression}}</div>
  <div class='reading'>{{Reading}}</div>
  {{#Audio}}<div class='audio'>{{Audio}}</div>{{/Audio}}
  <div class='img'>{{Image}}</div>
  <div class='ex'><b>例文:</b> {{SentenceJP}}</div>
  {{#SentenceAudio}}<div class='audio'>{{SentenceAudio}}</div>{{/SentenceAudio}}
</div>
""",
            "afmt": """\
<div class='front'>
  <div class='jp'>{{Expression}}</div>
  <div class='reading'>{{Reading}}</div>
  {{#Audio}}<div class='audio'>{{Audio}}</div>{{/Audio}}
  <div class='img'>{{Image}}</div>
</div>
<hr id='answer'>
  <div class='back'>
    <div class='en'><b>Meaning:</b> {{English}}</div>
    <div class='ex'><b>例文:</b> {{SentenceJP}}</div>
    <div class='ex'><b>E.g.:</b> {{SentenceEN}}</div>
    {{#SentenceAudio}}<div class='audio'>{{SentenceAudio}}</div>{{/SentenceAudio}}
    <div class='ex'><b>JP Dict:</b> {{DefinitionJP}}</div>
</div>
""",
        }
    ]
    return genanki.Model(model_id, name, fields=fields, templates=templates, css=css)


def make_note(model: genanki.Model, cd: CardData) -> genanki.Note:
    nid = deterministic_guid(cd.term, cd.reading or "", cd.english or "")
    return genanki.Note(
        model=model,
        fields=cd.to_fields(),
        guid=str(nid),
        tags=["VOCAB"],
    )


def build_grammar_model(
    model_id: int, name: str = DEFAULT_GRAMMAR_MODEL_NAME
) -> genanki.Model:
    css = """
    .question { font-family: 'Hiragino Kaku Gothic Pro', 'Meiryo', 'Noto Sans JP', sans-serif; font-size: 28px; }
    .example { margin-top: 12px; font-size: 18px; }
    .explanation { margin-top: 16px; font-size: 18px; }
    .audio { margin-top: 8px; font-size: 18px; }
    .card { text-align: left; }
    """
    fields = [
        {"name": "Question"},
        {"name": "Explanation"},
        {"name": "ExampleJP"},
        {"name": "ExampleAudio"},
        {"name": "ExampleEN"},
    ]
    templates = [
        {
            "name": "Grammar Card",
            "qfmt": """\
<div class='card'>
  <div class='question'>{{Question}}</div>
  {{#ExampleJP}}<div class='example'><b>例文:</b> {{ExampleJP}}</div>{{/ExampleJP}}
</div>
""",
            "afmt": """\
<div class='card'>
  <div class='question'>{{Question}}</div>
  <hr id='answer'>
  <div class='explanation'><b>解説:</b> {{Explanation}}</div>
  {{#ExampleJP}}<div class='example'><b>例文:</b> {{ExampleJP}}</div>{{/ExampleJP}}
  {{#ExampleAudio}}<div class='audio'>{{ExampleAudio}}</div>{{/ExampleAudio}}
  {{#ExampleEN}}<div class='example'><b>English:</b> {{ExampleEN}}</div>{{/ExampleEN}}
</div>
""",
        }
    ]
    return genanki.Model(model_id, name, fields=fields, templates=templates, css=css)


def make_grammar_note(model: genanki.Model, cd: GrammarCardData) -> genanki.Note:
    nid = deterministic_guid(cd.question, cd.example_jp or "", cd.example_en or "")
    return genanki.Note(
        model=model,
        fields=cd.to_fields(),
        guid=str(nid),
        tags=["GRAMMAR"],
    )


# -----------------------------
# Main logic
# -----------------------------

def gather_for_term(
    term: str,
    media_dir: Path,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> CardData:
    reading, english = fetch_jisho(term, debug=debug, logger=logger)
    if debug:
        message = (
            f"Parsed Jisho for '{term}': reading={reading!r}, english={english!r}"
        )
        if logger is not None:
            logger(message)
        else:
            console.log(f"[magenta]DEBUG {message}")
    jp_ex, en_ex = fetch_tatoeba_example(term, debug=debug, logger=logger)
    if debug:
        message = (
            f"Parsed Tatoeba for '{term}': sentence_jp={jp_ex!r}, sentence_en={en_ex!r}"
        )
        if logger is not None:
            logger(message)
        else:
            console.log(f"[magenta]DEBUG {message}")
    defi = fetch_wikipedia_ja_definition(term, debug=debug, logger=logger)
    if debug:
        message = f"Parsed Wikipedia definition for '{term}': definition={defi!r}"
        if logger is not None:
            logger(message)
        else:
            console.log(f"[magenta]DEBUG {message}")
    if not defi:
        defi = fetch_wiktionary_ja_definition(term, debug=debug, logger=logger)
        if debug:
            message = (
                f"Parsed Wiktionary definition for '{term}': definition={defi!r}"
            )
            if logger is not None:
                logger(message)
            else:
                console.log(f"[magenta]DEBUG {message}")
    if not defi:
        defi = fetch_kotobank_ja_definition(term, debug=debug, logger=logger)
        if debug:
            message = f"Parsed Kotobank definition for '{term}': definition={defi!r}"
            if logger is not None:
                logger(message)
            else:
                console.log(f"[magenta]DEBUG {message}")
    search_terms: List[str] = [term]
    if reading and reading not in search_terms:
        search_terms.append(reading)

    if english:
        # Use the first few English gloss candidates as fallbacks for image lookup.
        english_candidates = [
            e.strip() for e in re.split(r"(?i)[;,/]|\band\b", english) if e.strip()
        ]
        for candidate in english_candidates:
            if candidate not in search_terms:
                search_terms.append(candidate)
            if len(search_terms) >= 5:
                break

    img = ""
    for candidate in search_terms:
        img = fetch_duckduckgo_image(candidate, media_dir)
        if img:
            break

    audio = generate_term_audio(term, reading, media_dir)
    sentence_audio = generate_sentence_audio(jp_ex, media_dir)

    return CardData(
        term=term,
        reading=reading,
        english=english,
        sentence_jp=jp_ex,
        sentence_en=en_ex,
        definition_ja=defi,
        image_filename=img,
        audio_filename=audio,
        sentence_audio_filename=sentence_audio,
    )


def save_config(
    config_path: Path, deck_id: int, model_id: int, deck_name: str, mode: InputMode
) -> None:
    data = {
        "deck_id": deck_id,
        "model_id": model_id,
        "deck_name": deck_name,
        "mode": mode.value,
    }
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path: Path) -> Tuple[int, int, str, InputMode, bool]:
    j = json.loads(config_path.read_text(encoding="utf-8"))
    mode_raw = j.get("mode")
    missing_mode = "mode" not in j
    if mode_raw is None:
        mode = InputMode.VOCABULARY
    else:
        try:
            mode = InputMode(mode_raw)
        except ValueError as exc:  # pragma: no cover - config corrupted
            raise BuildError(
                f"Unsupported mode '{mode_raw}' in config {config_path}. Delete the config or build a new deck."
            ) from exc
    return (
        int(j["deck_id"]),
        int(j["model_id"]),
        str(j["deck_name"]),
        mode,
        missing_mode,
    )


def run_builder(
    params: BuildParams, reporter: Optional[BuildReporter] = None
) -> BuildResult:
    reporter = reporter or NullBuildReporter()

    out_dir = params.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / MEDIA_DIR_NAME
    media_dir.mkdir(parents=True, exist_ok=True)

    csv_file = params.csv_path
    if not csv_file.exists():
        raise BuildError(f"CSV not found: {csv_file}")

    config_path = params.config_path or (out_dir / CONFIG_FILE)
    deck_name = params.deck_name

    if params.new_deck or not config_path.exists():
        deck_id = random.randrange(1 << 30, 1 << 31)
        model_id = random.randrange(1 << 30, 1 << 31)
        save_config(config_path, deck_id, model_id, deck_name, params.mode)
        reporter.info(f"New deck config saved to {config_path}")
    else:
        deck_id, model_id, saved_deck_name, saved_mode, missing_mode = load_config(config_path)
        if params.mode != saved_mode:
            raise BuildError(
                "Config mode mismatch: the existing config was created for "
                f"'{saved_mode.value}' but the current build requested '{params.mode.value}'. "
                "Use --new-deck or provide a different config file."
            )
        if deck_name == DEFAULT_DECK_NAME:
            deck_name = saved_deck_name
        if missing_mode or deck_name != saved_deck_name:
            save_config(config_path, deck_id, model_id, deck_name, params.mode)
        reporter.info(f"Loaded existing config from {config_path}")

    deck = genanki.Deck(deck_id, deck_name)

    media_files: List[str] = []
    added = 0

    if params.mode is InputMode.VOCABULARY:
        model = build_model(model_id)
        terms = read_csv_single_column(csv_file)
        if not terms:
            raise BuildError("No terms found in CSV. Exiting.", exit_code=0)

        card_data_list: List[CardData] = []

        reporter.progress_start(len(terms), description="Fetching data...")
        debug_logger = reporter.debug if params.debug else None
        try:
            for term in terms:
                cd = gather_for_term(
                    term, media_dir, debug=params.debug, logger=debug_logger
                )
                card_data_list.append(cd)
                if cd.image_filename:
                    media_files.append(str(media_dir / cd.image_filename))
                if cd.audio_filename:
                    media_files.append(str(media_dir / cd.audio_filename))
                if cd.sentence_audio_filename:
                    media_files.append(str(media_dir / cd.sentence_audio_filename))
                reporter.progress_advance()
        finally:
            reporter.progress_finish()

        for cd in card_data_list:
            note = make_note(model, cd)
            try:
                deck.add_note(note)
                added += 1
            except Exception as e:
                reporter.warning(f"Skipped note for '{cd.term}': {e}")

        total_terms = len(terms)

    else:
        model = build_grammar_model(model_id)
        grammar_cards = read_grammar_csv(csv_file)
        if not grammar_cards:
            raise BuildError("No grammar entries found in CSV. Exiting.", exit_code=0)

        reporter.progress_start(len(grammar_cards), description="Adding grammar notes...")
        try:
            for gc in grammar_cards:
                example_audio = generate_sentence_audio(gc.example_jp, media_dir)
                gc.example_audio_filename = example_audio
                if example_audio:
                    media_files.append(str(media_dir / example_audio))
                note = make_grammar_note(model, gc)
                try:
                    deck.add_note(note)
                    added += 1
                except Exception as e:
                    reporter.warning(f"Skipped grammar note for '{gc.question}': {e}")
                finally:
                    reporter.progress_advance()
        finally:
            reporter.progress_finish()

        total_terms = len(grammar_cards)

    apkg_name = f"{safe_filename(deck_name)}.apkg"
    apkg_path = out_dir / apkg_name
    pkg = genanki.Package(deck)
    pkg.media_files = media_files
    pkg.write_to_file(str(apkg_path))

    reporter.info(f"Deck package created at {apkg_path}")

    return BuildResult(
        deck_name=deck_name,
        deck_id=deck_id,
        model_id=model_id,
        apkg_path=apkg_path,
        config_path=config_path,
        total_terms=total_terms,
        notes_added=added,
        media_files=media_files,
        mode=params.mode,
    )


@app.command()
def build(
    csv_path: str = typer.Option(
        ..., prompt=True, help="Path to CSV. Vocabulary mode expects one term per row; grammar mode expects question/explanation/example columns."
    ),
    output_dir: str = typer.Option(
        "./out", prompt="Output directory", help="Where to save the .apkg and media."
    ),
    new_deck: bool = typer.Option(True, help="Create a new deck (True) or append to an existing Anki deck by reusing IDs (False)."),
    deck_name: str = typer.Option(
        DEFAULT_DECK_NAME,
        prompt="Deck name",
        help="Deck name (used for new deck or when overriding config).",
    ),
    config: Optional[str] = typer.Option(None, help=f"Config JSON with deck_id/model_id (default: {CONFIG_FILE})."),
    debug: bool = typer.Option(
        False, "--debug", help="Print summarized API responses and parsed text values."
    ),
    mode: InputMode = typer.Option(
        InputMode.VOCABULARY,
        "--mode",
        prompt="Input mode",
        case_sensitive=False,
        help="Choose 'vocabulary' for enriched word cards or 'grammar' for explanation cards.",
    ),
):
    """Build or append an Anki deck from a CSV source of Japanese vocabulary or grammar prompts."""
    params = BuildParams(
        csv_path=Path(csv_path),
        output_dir=Path(output_dir),
        new_deck=new_deck,
        deck_name=deck_name,
        config_path=Path(config) if config else None,
        debug=debug,
        mode=mode,
    )
    reporter = RichBuildReporter(console)
    try:
        result = run_builder(params, reporter)
    except BuildError as exc:
        console.print(f"[red]{exc}")
        raise typer.Exit(code=exc.exit_code)
    except Exception as exc:
        console.print(f"[red]Unexpected error:[/] {exc}")
        raise typer.Exit(code=1)

    # Summary
    table = Table(title="Build Summary", show_lines=True)
    table.add_column("Metric", justify="right")
    table.add_column("Value", justify="left")
    table.add_row("Mode", result.mode.value.title())
    table.add_row("Terms in CSV", str(result.total_terms))
    table.add_row("Notes added", str(result.notes_added))
    table.add_row("Media files", str(len(result.media_files)))
    table.add_row("Output", str(result.apkg_path))
    table.add_row("Config", str(result.config_path))
    console.print(table)

    console.print("[green]Done![/] Import the .apkg into Anki. If you used the same config (deck/model IDs), new cards will append into the existing deck.")

    if debug:
        log_path = params.output_dir / "anki_deck_builder_debug_log.txt"
        log_text = console.export_text(clear=False, styles=False)
        log_path.write_text(log_text, encoding="utf-8")
        console.print(f"[cyan]Debug log saved to[/] {log_path}")


if __name__ == "__main__":
    app()
