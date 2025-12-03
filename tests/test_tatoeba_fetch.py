import json
import sys
import types
from typing import Any, Dict, List, Optional


def _install_stub_dependencies() -> None:
    if "rich.console" not in sys.modules:
        console_module = types.ModuleType("rich.console")

        class _Console:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

            def print(self, *args: Any, **kwargs: Any) -> None:
                return None

            def log(self, *args: Any, **kwargs: Any) -> None:
                return None

        console_module.Console = _Console  # type: ignore[attr-defined]
        sys.modules["rich.console"] = console_module

    if "rich.progress" not in sys.modules:
        progress_module = types.ModuleType("rich.progress")

        class _StubComponent:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

        class _Progress:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

            def __enter__(self) -> "_Progress":
                return self

            def __exit__(self, *args: Any) -> bool:
                return False

            def add_task(self, *args: Any, **kwargs: Any) -> int:
                return 0

            def update(self, *args: Any, **kwargs: Any) -> None:
                return None

            def stop(self) -> None:
                return None

        progress_module.Progress = _Progress  # type: ignore[attr-defined]
        progress_module.SpinnerColumn = _StubComponent  # type: ignore[attr-defined]
        progress_module.TextColumn = _StubComponent  # type: ignore[attr-defined]
        progress_module.BarColumn = _StubComponent  # type: ignore[attr-defined]
        progress_module.TimeElapsedColumn = _StubComponent  # type: ignore[attr-defined]
        progress_module.TimeRemainingColumn = _StubComponent  # type: ignore[attr-defined]
        sys.modules["rich.progress"] = progress_module

    if "rich.table" not in sys.modules:
        table_module = types.ModuleType("rich.table")

        class _Table:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

            def add_column(self, *args: Any, **kwargs: Any) -> None:
                return None

            def add_row(self, *args: Any, **kwargs: Any) -> None:
                return None

        table_module.Table = _Table  # type: ignore[attr-defined]
        sys.modules["rich.table"] = table_module

    if "slugify" not in sys.modules:
        slugify_module = types.ModuleType("slugify")

        def _slugify(value: str) -> str:
            return value

        slugify_module.slugify = _slugify  # type: ignore[attr-defined]
        sys.modules["slugify"] = slugify_module

    if "genanki" not in sys.modules:
        genanki_module = types.ModuleType("genanki")

        class _StubGenanki:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

        genanki_module.Package = _StubGenanki  # type: ignore[attr-defined]
        genanki_module.Note = _StubGenanki  # type: ignore[attr-defined]
        genanki_module.Model = _StubGenanki  # type: ignore[attr-defined]
        genanki_module.Deck = _StubGenanki  # type: ignore[attr-defined]
        sys.modules["genanki"] = genanki_module

    if "unidecode" not in sys.modules:
        unidecode_module = types.ModuleType("unidecode")

        def _unidecode(value: Any) -> str:
            return str(value)

        unidecode_module.unidecode = _unidecode  # type: ignore[attr-defined]
        sys.modules["unidecode"] = unidecode_module


_install_stub_dependencies()

import pytest

import anki_deck_builder
from anki_deck_builder import fetch_tatoeba_example


class DummyResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


def _mocked_get_factory(responses: List[Dict[str, Any]], call_recorder: List[Dict[str, Any]]):
    def _mocked_get(url: str, params: Dict[str, Any], headers: Dict[str, Any], timeout: int):
        call_recorder.append(dict(params))
        index = len(call_recorder) - 1
        payload = responses[min(index, len(responses) - 1)]
        return DummyResponse(payload)

    return _mocked_get


def test_fetch_tatoeba_prefers_native_and_longest(monkeypatch):
    calls: List[Dict[str, Any]] = []
    responses = [
        {
            "results": [
                {
                    "text": "短い",  # len without whitespace: 2
                    "translations": [{"lang": "eng", "text": "short"}],
                },
                {
                    "text": "これは 長い 文",  # len without whitespace: 6
                    "translations": [{"lang": "eng", "text": "long"}],
                },
            ]
        }
    ]

    mock_requests = types.SimpleNamespace(get=_mocked_get_factory(responses, calls))
    monkeypatch.setattr(anki_deck_builder, "requests", mock_requests)

    jp, en = fetch_tatoeba_example("猫")
    assert (jp, en) == ("これは 長い 文", "long")
    assert len(calls) == 1
    assert calls[0].get("native") == "yes"


def test_fetch_tatoeba_falls_back_without_native(monkeypatch):
    calls: List[Dict[str, Any]] = []
    responses = [
        {
            "results": [
                {
                    "text": "ネイティブのみ",
                    "translations": [{"lang": "fra", "text": "français"}],
                }
            ]
        },
        {
            "results": [
                {
                    "text": "短い",  # len 2
                    "translations": [[{"lang": "eng", "text": "short"}]],
                },
                {
                    "text": "  これは 長い サンプル  ",  # len 8 after stripping whitespace
                    "translations": [[{"lang": "eng", "text": "long example"}]],
                },
            ]
        },
    ]

    mock_requests = types.SimpleNamespace(get=_mocked_get_factory(responses, calls))
    monkeypatch.setattr(anki_deck_builder, "requests", mock_requests)

    jp, en = fetch_tatoeba_example("犬")
    assert (jp, en) == ("これは 長い サンプル", "long example")
    assert len(calls) == 2
    assert calls[0].get("native") == "yes"
    assert not calls[1].get("native")


def test_fetch_tatoeba_handles_translation_dict(monkeypatch):
    calls: List[Dict[str, Any]] = []
    responses = [
        {
            "results": [
                {
                    "text": "辞書",  # len 2
                    "translations": {
                        "eng": [
                            {"text": "dictionary"},
                            {"text": "reference"},
                        ]
                    },
                }
            ]
        }
    ]

    mock_requests = types.SimpleNamespace(get=_mocked_get_factory(responses, calls))
    monkeypatch.setattr(anki_deck_builder, "requests", mock_requests)

    jp, en = fetch_tatoeba_example("辞書")
    assert (jp, en) == ("辞書", "dictionary")
    assert len(calls) == 1
    assert calls[0].get("native") == "yes"


def test_fetch_tatoeba_filters_by_token_match(monkeypatch):
    calls: List[Dict[str, Any]] = []
    responses = [
        {
            "results": [
                {
                    "text": "いくらかかる？",
                    "translations": [{"lang": "eng", "text": "how much does it cost?"}],
                },
                {
                    "text": "明日いくよ",
                    "translations": [{"lang": "eng", "text": "I will go tomorrow"}],
                },
            ]
        }
    ]

    class DummyToken:
        def __init__(self, surface: str, lemma: Optional[str] = None) -> None:
            self.surface = surface
            lemma_value = lemma if lemma is not None else surface
            self.feature = ["*"] * 7
            self.feature[6] = lemma_value

    class DummyTokenizer:
        def __call__(self, text: str):
            normalized = text.replace("？", "")
            if "いくら" in normalized:
                return [DummyToken("いくら"), DummyToken("かかる")]
            if "いく" in normalized:
                return [DummyToken("明日"), DummyToken("いく"), DummyToken("よ")]
            return [DummyToken(normalized)]

    monkeypatch.setattr(
        anki_deck_builder, "_get_japanese_tokenizer", lambda: DummyTokenizer()
    )
    mock_requests = types.SimpleNamespace(get=_mocked_get_factory(responses, calls))
    monkeypatch.setattr(anki_deck_builder, "requests", mock_requests)

    jp, en = fetch_tatoeba_example("いく")
    assert (jp, en) == ("明日いくよ", "I will go tomorrow")
    assert len(calls) == 1
    assert calls[0].get("native") == "yes"
