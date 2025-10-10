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
  * JP monolingual definition: Goo 国語 dictionary (fallback: Japanese Wikipedia)
  * Related image: Wikimedia Commons (Commons) thumbnail

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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from slugify import slugify
import genanki
from unidecode import unidecode

from goo_dictionary import extract_first_goo_definition

app = typer.Typer(add_completion=False)
console = Console()

# -----------------------------
# Config / Constants
# -----------------------------
USER_AGENT = "AnkiDeckBuilder/1.0 (+https://github.com/)"
HEADERS = {"User-Agent": USER_AGENT}

JISHO_URL = "https://jisho.org/api/v1/search/words"
TATOEBA_URL = "https://tatoeba.org/eng/api_v0/search"
GOO_DICTIONARY_ENTRY_URL = "https://dictionary.goo.ne.jp/word/{term}/"
GOO_DICTIONARY_SEARCH_URL = "https://dictionary.goo.ne.jp/srch/all/{term}/m0u/"
WIKIPEDIA_JA_API = "https://ja.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

DEFAULT_MODEL_NAME = "JP Word w/ Image + Examples (MVP)"
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

    def to_fields(self) -> List[str]:
        # Order must match the model fields list below
        img_tag = f'<img src="{self.image_filename}" />' if self.image_filename else ''
        return [
            self.term,
            self.reading,
            self.english,
            self.sentence_jp,
            self.sentence_en,
            self.definition_ja,
            f"<div>{img_tag}</div>",
        ]

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


def safe_filename(base: str) -> str:
    s = slugify(base, lowercase=False, separator="_")
    return s or hashlib.md5(base.encode("utf-8")).hexdigest()[:10]


def deterministic_guid(*parts: str) -> int:
    h = hashlib.md5("::".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)  # genanki Note/Deck IDs are 32-bit ints OK


# -----------------------------
# Fetchers (no-auth public sources)
# -----------------------------

def fetch_jisho(term: str, debug: bool = False) -> Tuple[str, str]:
    """Return (reading_kana, english_glosses) from Jisho for a term."""
    try:
        resp = requests.get(JISHO_URL, params={"keyword": term}, headers=HEADERS, timeout=15)
        if debug:
            console.log(
                f"[cyan]DEBUG Jisho response for '{term}':[/] {resp.text}"
            )
        resp.raise_for_status()
        data = resp.json()
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


def fetch_tatoeba_example(term: str, debug: bool = False) -> Tuple[str, str]:
    """Return (jp_sentence, en_translation) from Tatoeba.
    Handles API shapes where 'translations' may be a list of dicts or grouped lists.
    """
    try:
        params = {
            "from": "jpn",
            "query": term,
            "to": "eng",
            "trans_filter": "limit",
            "trans_link": "direct",
            "trans_to": "eng",
        }
        r = requests.get(TATOEBA_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        if debug:
            console.log(
                f"[cyan]DEBUG Tatoeba response for '{term}':[/] {r.text}"
            )
        j = r.json()
        results = j.get("results", [])
        if not isinstance(results, list):
            return "", ""
        for res in results:
            if not isinstance(res, dict):
                continue
            jp_text = (res.get("text") or "").strip()
            trans = res.get("translations", [])
            # Case A: list of dicts with 'lang' and 'text'
            if isinstance(trans, list):
                # translations can be a flat list of dicts OR a list of lists
                flat: List[dict] = []
                for t in trans:
                    if isinstance(t, dict):
                        flat.append(t)
                    elif isinstance(t, list):
                        flat.extend([x for x in t if isinstance(x, dict)])
                for t in flat:
                    if t.get("lang") in ("eng", "en") and t.get("text"):
                        return jp_text, t.get("text", "").strip()
            # Case B: dict keyed by language codes
            if isinstance(trans, dict):
                eng_list = trans.get("eng") or trans.get("en")
                if isinstance(eng_list, list) and eng_list:
                    first = eng_list[0]
                    if isinstance(first, dict) and first.get("text"):
                        return jp_text, first.get("text", "").strip()
        return "", ""
    except Exception as e:
        console.log(f"[yellow]Tatoeba fetch failed for '{term}': {e}")
        return "", ""


def fetch_goo_ja_definition(term: str, debug: bool = False) -> str:
    """Return a short JP definition from Goo's 国語 dictionary."""
    encoded = quote(term, safe="")
    for url_template in (GOO_DICTIONARY_ENTRY_URL, GOO_DICTIONARY_SEARCH_URL):
        url = url_template.format(term=encoded)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            if debug:
                console.log(
                    f"[cyan]DEBUG Goo response for '{term}' at {url}:[/] {resp.text}"
                )
        except Exception as e:
            console.log(f"[yellow]Goo dictionary fetch failed for '{term}' at {url}: {e}")
            continue

        definition = extract_first_goo_definition(resp.text)
        if definition:
            return definition[:400]
    return ""


def fetch_wikipedia_ja_definition(term: str, debug: bool = False) -> str:
    """Return a short JP extract from Japanese Wikipedia (if any)."""
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
        if debug:
            console.log(
                f"[cyan]DEBUG Wikipedia JA response for '{term}':[/] {r.text}"
            )
        j = r.json()
        pages = (j.get("query", {}) or {}).get("pages", {})
        if not pages:
            return ""
        page = next(iter(pages.values()))
        extract = (page or {}).get("extract", "").strip()
        # Keep only the first sentence for brevity
        if extract:
            m = re.split(r"(?<=。)", extract)
            return (m[0] if m else extract)[:400]
        return ""
    except Exception as e:
        console.log(f"[yellow]Wikipedia JA fetch failed for '{term}': {e}")
        return ""


def fetch_commons_image(term: str, media_dir: Path) -> str:
    """Download first Commons image matching the term. Return local filename or ''."""
    try:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": term,
            "gsrnamespace": 6,  # File namespace
            "gsrlimit": 1,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 600,
        }
        r = requests.get(COMMONS_API, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        j = r.json()
        pages = (j.get("query", {}) or {}).get("pages", {})
        if not pages:
            return ""
        page = next(iter(pages.values()))
        ii = (page.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        if not url:
            return ""
        # Download
        fn = safe_filename(f"{term}_img") + os.path.splitext(url)[1].split("?")[0]
        dest = media_dir / fn
        with requests.get(url, headers=HEADERS, timeout=30, stream=True) as img:
            img.raise_for_status()
            with open(dest, "wb") as out:
                for chunk in img.iter_content(chunk_size=65536):
                    if chunk:
                        out.write(chunk)
        return fn
    except Exception as e:
        console.log(f"[yellow]Commons image fetch failed for '{term}': {e}")
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
    img { max-width: 100%; height: auto; }
    .front { text-align: center; }
    .back { text-align: left; }
    """
    fields = [
        {"name": "Expression"},
        {"name": "Reading"},
        {"name": "English"},
        {"name": "SentenceJP"},
        {"name": "SentenceEN"},
        {"name": "DefinitionJP"},
        {"name": "Image"},
    ]
    templates = [
        {
            "name": "Card 1",
            "qfmt": (
                "<div class='front'>"
                "<div class='jp'>{{Expression}}</div>"
                "<div class='reading'>{{Reading}}</div>"
                "<div class='img'>{{Image}}</div>"
                "</div>"
            ),
            "afmt": (
                "{{FrontSide}}<hr id='answer'>"
                "<div class='back'>"
                "<div class='en'><b>English:</b> {{English}}</div>"
                "<div class='ex'><b>例文:</b> {{SentenceJP}}</div>"
                "<div class='ex'><b>EN:</b> {{SentenceEN}}</div>"
                "<div class='def'><b>国語:</b> {{DefinitionJP}}</div>"
                "</div>"
            ),
        }
    ]
    return genanki.Model(model_id, name, fields=fields, templates=templates, css=css)


def make_note(model: genanki.Model, cd: CardData) -> genanki.Note:
    nid = deterministic_guid(cd.term, cd.reading or "", cd.english or "")
    return genanki.Note(model=model, fields=cd.to_fields(), guid=str(nid))


# -----------------------------
# Main logic
# -----------------------------

def gather_for_term(term: str, media_dir: Path, debug: bool = False) -> CardData:
    reading, english = fetch_jisho(term, debug=debug)
    if debug:
        console.log(
            f"[magenta]DEBUG Parsed Jisho for '{term}': reading={reading!r}, english={english!r}"
        )
    jp_ex, en_ex = fetch_tatoeba_example(term, debug=debug)
    if debug:
        console.log(
            f"[magenta]DEBUG Parsed Tatoeba for '{term}': sentence_jp={jp_ex!r}, sentence_en={en_ex!r}"
        )
    defi = fetch_goo_ja_definition(term, debug=debug)
    if debug:
        console.log(
            f"[magenta]DEBUG Parsed Goo definition for '{term}': definition={defi!r}"
        )
    if not defi:
        defi = fetch_wikipedia_ja_definition(term, debug=debug)
        if debug:
            console.log(
                f"[magenta]DEBUG Parsed Wikipedia definition for '{term}': definition={defi!r}"
            )
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
        img = fetch_commons_image(candidate, media_dir)
        if img:
            break
    return CardData(term=term, reading=reading, english=english, sentence_jp=jp_ex, sentence_en=en_ex, definition_ja=defi, image_filename=img)


def save_config(config_path: Path, deck_id: int, model_id: int, deck_name: str):
    data = {"deck_id": deck_id, "model_id": model_id, "deck_name": deck_name}
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config(config_path: Path) -> Tuple[int, int, str]:
    j = json.loads(config_path.read_text(encoding="utf-8"))
    return int(j["deck_id"]), int(j["model_id"]), str(j["deck_name"])  # type: ignore


@app.command()
def build(
    csv_path: str = typer.Option(..., prompt=True, help="Path to CSV with one Japanese term per row."),
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
    debug: bool = typer.Option(False, "--debug", help="Print raw API responses and parsed text values."),
):
    """Build or append an Anki deck from a CSV list of Japanese terms."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / MEDIA_DIR_NAME
    media_dir.mkdir(parents=True, exist_ok=True)

    csv_file = Path(csv_path)
    if not csv_file.exists():
        console.print(f"[red]CSV not found:[/] {csv_file}")
        raise typer.Exit(code=1)

    # Determine deck/model IDs
    config_path = Path(config) if config else (out_dir / CONFIG_FILE)
    if new_deck or not config_path.exists():
        # Create fresh IDs; store config to allow future appends
        deck_id = random.randrange(1 << 30, 1 << 31)
        model_id = random.randrange(1 << 30, 1 << 31)
        save_config(config_path, deck_id, model_id, deck_name)
        console.print(f"[green]New deck config saved to[/] {config_path}")
    else:
        deck_id, model_id, saved_deck_name = load_config(config_path)
        if deck_name == DEFAULT_DECK_NAME:
            deck_name = saved_deck_name
        console.print(f"[cyan]Loaded existing config from[/] {config_path}")

    deck = genanki.Deck(deck_id, deck_name)
    model = build_model(model_id)

    # Read terms
    terms = read_csv_single_column(csv_file)
    if not terms:
        console.print("[yellow]No terms found in CSV. Exiting.")
        raise typer.Exit(code=0)

    # Fetch & build notes with progress
    media_files: List[str] = []
    card_data_list: List[CardData] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching data...", total=len(terms))
        for term in terms:
            cd = gather_for_term(term, media_dir, debug=debug)
            card_data_list.append(cd)
            if cd.image_filename:
                media_files.append(str(media_dir / cd.image_filename))
            progress.advance(task)

    # Add notes
    added = 0
    for cd in card_data_list:
        note = make_note(model, cd)
        try:
            deck.add_note(note)
            added += 1
        except Exception as e:
            console.log(f"[yellow]Skipped note for '{cd.term}': {e}")

    # Package deck
    apkg_name = f"{safe_filename(deck_name)}.apkg"
    apkg_path = out_dir / apkg_name
    pkg = genanki.Package(deck)
    pkg.media_files = media_files
    pkg.write_to_file(str(apkg_path))

    # Summary
    table = Table(title="Build Summary", show_lines=True)
    table.add_column("Metric", justify="right")
    table.add_column("Value", justify="left")
    table.add_row("Terms in CSV", str(len(terms)))
    table.add_row("Notes added", str(added))
    table.add_row("Media files", str(len(media_files)))
    table.add_row("Output", str(apkg_path))
    table.add_row("Config", str(config_path))
    console.print(table)

    console.print("[green]Done![/] Import the .apkg into Anki. If you used the same config (deck/model IDs), new cards will append into the existing deck.")


if __name__ == "__main__":
    app()
