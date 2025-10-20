from pathlib import Path

import pytest

from anki_deck_builder import (
    BuildParams,
    BuildResult,
    BuildError,
    InputMode,
    read_grammar_csv,
    run_builder,
    save_config,
)


def test_read_grammar_csv_parses_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "grammar.csv"
    csv_path.write_text(
        "Question,Explanation,Example JP,Example EN\n"
        "What is です?,It means 'to be',これはペンです,This is a pen\n",
        encoding="utf-8",
    )

    rows = read_grammar_csv(csv_path)

    assert len(rows) == 1
    row = rows[0]
    assert row.question == "What is です?"
    assert row.explanation == "It means 'to be'"
    assert row.example_jp == "これはペンです"
    assert row.example_en == "This is a pen"
    assert row.example_audio_filename == ""


def test_run_builder_grammar_mode_skips_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_path = tmp_path / "grammar_cards.csv"
    csv_path.write_text(
        "question,explanation,example_jp,example_en\n"
        "〜ている,Progressive aspect,音楽を聞いている,Listening to music\n"
        "〜なければならない,Obligation,,Must do\n",
        encoding="utf-8",
    )

    import anki_deck_builder as builder

    def _fail(*_args, **_kwargs):  # pragma: no cover - ensures not called
        raise AssertionError("Network helper should not be called in grammar mode")

    for name in [
        "fetch_jisho",
        "fetch_tatoeba_example",
        "fetch_wikipedia_ja_definition",
        "fetch_wiktionary_ja_definition",
        "fetch_kotobank_ja_definition",
        "fetch_duckduckgo_image",
        "generate_term_audio",
        "gather_for_term",
    ]:
        monkeypatch.setattr(builder, name, _fail)

    audio_counter = 0

    def _fake_generate_sentence_audio(sentence: str, media_dir: Path) -> str:
        nonlocal audio_counter
        if not sentence:
            return ""
        audio_counter += 1
        filename = f"example_audio_{audio_counter}.mp3"
        (media_dir / filename).write_bytes(b"audio")
        return filename

    monkeypatch.setattr(
        builder, "generate_sentence_audio", _fake_generate_sentence_audio
    )

    created_packages: list[Path] = []

    def _fake_write_to_file(self, path: str) -> None:  # type: ignore[override]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"dummy")
        created_packages.append(target)

    monkeypatch.setattr(builder.genanki.Package, "write_to_file", _fake_write_to_file)

    out_dir = tmp_path / "out"

    params = BuildParams(
        csv_path=csv_path,
        output_dir=out_dir,
        new_deck=True,
        deck_name="Grammar Deck",
        config_path=None,
        debug=False,
        mode=InputMode.GRAMMAR,
    )

    result: BuildResult = run_builder(params)

    assert result.mode is InputMode.GRAMMAR
    assert result.total_terms == 2
    assert result.notes_added == 2
    expected_audio = tmp_path / "out" / "media" / "example_audio_1.mp3"
    assert result.media_files == [str(expected_audio)]
    assert result.apkg_path.exists()
    assert created_packages and created_packages[0] == result.apkg_path


def test_run_builder_rejects_mismatched_config(tmp_path: Path) -> None:
    csv_path = tmp_path / "grammar_cards.csv"
    csv_path.write_text(
        "question,explanation,example_jp,example_en\n"
        "〜ている,Progressive aspect,音楽を聞いている,Listening to music\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    config_path = out_dir / "anki_deck_builder.config.json"
    save_config(config_path, deck_id=1234, model_id=5678, deck_name="Vocab Deck", mode=InputMode.VOCABULARY)

    params = BuildParams(
        csv_path=csv_path,
        output_dir=out_dir,
        new_deck=False,
        deck_name="Grammar Deck",
        config_path=config_path,
        debug=False,
        mode=InputMode.GRAMMAR,
    )

    with pytest.raises(BuildError) as excinfo:
        run_builder(params)

    assert "mode mismatch" in str(excinfo.value).lower()
