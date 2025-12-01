from pathlib import Path

import pytest

import anki_deck_builder as builder
from anki_deck_builder import BuildParams, BuildResult, InputMode


class CollectingReporter(builder.NullBuildReporter):
    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []

    def warning(self, message: str) -> None:  # type: ignore[override]
        self.warnings.append(message)


def test_run_builder_filters_missing_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "vocab.csv"
    csv_path.write_text("こんにちは\n", encoding="utf-8")

    media_dir = tmp_path / "out" / builder.MEDIA_DIR_NAME

    def _fake_gather_for_term(term: str, media_dir: Path, **_: object) -> builder.CardData:
        existing_audio = media_dir / "existing.mp3"
        existing_audio.write_bytes(b"audio")
        return builder.CardData(
            term=term,
            image_filename="missing.jpg",
            audio_filename=existing_audio.name,
        )

    monkeypatch.setattr(builder, "gather_for_term", _fake_gather_for_term)

    captured_media: list[str] = []

    def _fake_write_to_file(self, path: str) -> None:  # type: ignore[override]
        captured_media.extend(self.media_files)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"dummy")

    monkeypatch.setattr(builder.genanki.Package, "write_to_file", _fake_write_to_file)

    params = BuildParams(
        csv_path=csv_path,
        output_dir=tmp_path / "out",
        new_deck=True,
        deck_name="Test Deck",
        config_path=None,
        debug=False,
        mode=InputMode.VOCABULARY,
    )

    reporter = CollectingReporter()
    result: BuildResult = builder.run_builder(params, reporter)

    expected_media = str(media_dir / "existing.mp3")
    assert result.media_files == [expected_media]
    assert captured_media == [expected_media]
    assert any("missing.jpg" in warning for warning in reporter.warnings)

