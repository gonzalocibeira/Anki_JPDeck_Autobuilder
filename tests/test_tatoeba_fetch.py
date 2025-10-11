import json
from typing import Any, Dict, List

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

    monkeypatch.setattr(
        anki_deck_builder.requests,
        "get",
        _mocked_get_factory(responses, calls),
    )

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

    monkeypatch.setattr(
        anki_deck_builder.requests,
        "get",
        _mocked_get_factory(responses, calls),
    )

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

    monkeypatch.setattr(
        anki_deck_builder.requests,
        "get",
        _mocked_get_factory(responses, calls),
    )

    jp, en = fetch_tatoeba_example("辞書")
    assert (jp, en) == ("辞書", "dictionary")
    assert len(calls) == 1
    assert calls[0].get("native") == "yes"
