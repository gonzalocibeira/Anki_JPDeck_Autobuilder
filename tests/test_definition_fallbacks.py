from __future__ import annotations

import json
from typing import Any, Dict

import sys
import types

if "typer" not in sys.modules:
    class _DummyTyper:
        def __init__(self, *args, **kwargs):
            pass

        def command(self, *args, **kwargs):  # pragma: no cover - trivial decorator
            def decorator(func):
                return func

            return decorator

    class _DummyExit(Exception):
        def __init__(self, code: int = 0):
            self.code = code

    def _dummy_option(*args, **kwargs):  # pragma: no cover - placeholder
        return None

    sys.modules["typer"] = types.SimpleNamespace(
        Typer=lambda *args, **kwargs: _DummyTyper(),
        Option=_dummy_option,
        Exit=_DummyExit,
    )

if "rich" not in sys.modules:
    sys.modules["rich"] = types.ModuleType("rich")

if "rich.console" not in sys.modules:
    console_module = types.ModuleType("rich.console")

    class _DummyConsole:
        def __init__(self, *args, **kwargs):
            pass

        def log(self, *args, **kwargs):  # pragma: no cover - placeholder logging
            pass

    console_module.Console = _DummyConsole
    sys.modules["rich.console"] = console_module

if "rich.progress" not in sys.modules:
    progress_module = types.ModuleType("rich.progress")

    class _DummyProgress:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):  # pragma: no cover - context manager placeholder
            return self

        def __exit__(self, exc_type, exc, tb):  # pragma: no cover
            return False

        def add_task(self, *args, **kwargs):  # pragma: no cover
            return 0

        def update(self, *args, **kwargs):  # pragma: no cover
            pass

    class _DummyColumn:
        def __init__(self, *args, **kwargs):
            pass

    progress_module.Progress = _DummyProgress
    progress_module.SpinnerColumn = _DummyColumn
    progress_module.TextColumn = _DummyColumn
    progress_module.BarColumn = _DummyColumn
    progress_module.TimeElapsedColumn = _DummyColumn
    progress_module.TimeRemainingColumn = _DummyColumn
    sys.modules["rich.progress"] = progress_module

if "rich.table" not in sys.modules:
    table_module = types.ModuleType("rich.table")

    class _DummyTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):  # pragma: no cover
            pass

        def add_row(self, *args, **kwargs):  # pragma: no cover
            pass

    table_module.Table = _DummyTable
    sys.modules["rich.table"] = table_module

if "slugify" not in sys.modules:
    slugify_module = types.ModuleType("slugify")

    def _dummy_slugify(value: str, *, lowercase: bool = False, separator: str = "-") -> str:
        return value

    slugify_module.slugify = _dummy_slugify
    sys.modules["slugify"] = slugify_module

if "genanki" not in sys.modules:
    genanki_module = types.ModuleType("genanki")

    class _DummyModel:
        def __init__(self, *args, **kwargs):
            pass

    class _DummyNote:
        def __init__(self, *args, **kwargs):
            self.fields = kwargs.get("fields", [])

    class _DummyDeck:
        def __init__(self, *args, **kwargs):
            self._notes = []

        def add_note(self, note):  # pragma: no cover
            self._notes.append(note)

    class _DummyPackage:
        def __init__(self, deck):
            self.deck = deck

        def write_to_file(self, path):  # pragma: no cover
            pass

    genanki_module.Model = _DummyModel
    genanki_module.Note = _DummyNote
    genanki_module.Deck = _DummyDeck
    genanki_module.Package = _DummyPackage
    sys.modules["genanki"] = genanki_module

if "unidecode" not in sys.modules:
    unidecode_module = types.ModuleType("unidecode")
    unidecode_module.unidecode = lambda value: value
    sys.modules["unidecode"] = unidecode_module

if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")

    def _stub_get(*args, **kwargs):  # pragma: no cover - overwritten in tests
        raise RuntimeError("requests.get stub not replaced")

    requests_module.get = _stub_get
    sys.modules["requests"] = requests_module

import pytest

import anki_deck_builder as adb


class DummyResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:  # pragma: no cover - no-op in tests
        return None


def _patch_common_fetchers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adb, "fetch_jisho", lambda term, debug=False: ("よみ", "english"))
    monkeypatch.setattr(adb, "fetch_tatoeba_example", lambda term, debug=False: ("例文", "Example"))
    monkeypatch.setattr(adb, "fetch_duckduckgo_image", lambda term, media_dir: "")


def test_fetch_wiktionary_ja_definition_parses_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    term = "テスト"
    payload = {
        "query": {
            "pages": {
                "123": {
                    "pageid": 123,
                    "title": term,
                    "extract": "==日本語==\n===名詞===\n# 試験などを意味する言葉。",
                }
            }
        }
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == adb.WIKTIONARY_JA_API
        assert params["titles"] == term
        return DummyResponse(payload)

    monkeypatch.setattr(adb.requests, "get", fake_get)

    definition = adb.fetch_wiktionary_ja_definition(term)
    assert definition == "試験などを意味する言葉。"


def test_gather_for_term_uses_wikipedia_definition_first(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _patch_common_fetchers(monkeypatch)

    calls = {"wikipedia": 0, "wiktionary": 0, "goo": 0}

    monkeypatch.setattr(
        adb,
        "fetch_wikipedia_ja_definition",
        lambda term, debug=False: calls.__setitem__("wikipedia", calls["wikipedia"] + 1) or "Wiki",
    )
    monkeypatch.setattr(
        adb,
        "fetch_wiktionary_ja_definition",
        lambda term, debug=False: calls.__setitem__("wiktionary", calls["wiktionary"] + 1) or "Wiktionary",
    )
    monkeypatch.setattr(
        adb,
        "fetch_goo_ja_definition",
        lambda term, debug=False: calls.__setitem__("goo", calls["goo"] + 1) or "Goo",
    )

    card = adb.gather_for_term("語", tmp_path)

    assert card.definition_ja == "Wiki"
    assert calls == {"wikipedia": 1, "wiktionary": 0, "goo": 0}


def test_gather_for_term_falls_back_to_wiktionary(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _patch_common_fetchers(monkeypatch)

    calls = {"wikipedia": 0, "wiktionary": 0, "goo": 0}

    monkeypatch.setattr(
        adb,
        "fetch_wikipedia_ja_definition",
        lambda term, debug=False: calls.__setitem__("wikipedia", calls["wikipedia"] + 1) or "",
    )
    monkeypatch.setattr(
        adb,
        "fetch_wiktionary_ja_definition",
        lambda term, debug=False: calls.__setitem__("wiktionary", calls["wiktionary"] + 1) or "Wiktionary",
    )
    monkeypatch.setattr(
        adb,
        "fetch_goo_ja_definition",
        lambda term, debug=False: calls.__setitem__("goo", calls["goo"] + 1) or "Goo",
    )

    card = adb.gather_for_term("語", tmp_path)

    assert card.definition_ja == "Wiktionary"
    assert calls == {"wikipedia": 1, "wiktionary": 1, "goo": 0}


def test_gather_for_term_falls_back_to_goo(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _patch_common_fetchers(monkeypatch)

    calls = {"wikipedia": 0, "wiktionary": 0, "goo": 0}

    monkeypatch.setattr(
        adb,
        "fetch_wikipedia_ja_definition",
        lambda term, debug=False: calls.__setitem__("wikipedia", calls["wikipedia"] + 1) or "",
    )
    monkeypatch.setattr(
        adb,
        "fetch_wiktionary_ja_definition",
        lambda term, debug=False: calls.__setitem__("wiktionary", calls["wiktionary"] + 1) or "",
    )
    monkeypatch.setattr(
        adb,
        "fetch_goo_ja_definition",
        lambda term, debug=False: calls.__setitem__("goo", calls["goo"] + 1) or "Goo",
    )

    card = adb.gather_for_term("語", tmp_path)

    assert card.definition_ja == "Goo"
    assert calls == {"wikipedia": 1, "wiktionary": 1, "goo": 1}
