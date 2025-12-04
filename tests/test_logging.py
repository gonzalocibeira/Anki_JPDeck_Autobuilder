from datetime import datetime

from anki_deck_builder import (
    BuildParams,
    BuildResult,
    Console,
    InputMode,
    RichBuildReporter,
    write_run_log,
)


def test_rich_build_reporter_collects_warnings_and_errors():
    console = Console(record=True)
    reporter = RichBuildReporter(console)

    reporter.warning("first warning")
    reporter.error("critical error")

    assert reporter.warnings == ["first warning"]
    assert reporter.errors == ["critical error"]


def test_write_run_log_adds_summary_and_errors(tmp_path):
    csv_path = tmp_path / "terms.csv"
    csv_path.write_text("hello", encoding="utf-8")

    console = Console(record=True)
    reporter = RichBuildReporter(console)
    reporter.warning("warned about something")
    reporter.error("missing media file")
    console.print("console line")

    result = BuildResult(
        deck_name="Deck",
        deck_id=123,
        model_id=456,
        apkg_path=tmp_path / "Deck.apkg",
        config_path=tmp_path / "anki_deck_builder.config.json",
        total_terms=10,
        notes_added=9,
        media_files=["one", "two"],
        mode=InputMode.VOCABULARY,
    )

    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    log_path = write_run_log(
        params=BuildParams(
            csv_path=csv_path, output_dir=tmp_path, new_deck=True, deck_name="Deck"
        ),
        reporter=reporter,
        console=console,
        result=result,
        failure_message=None,
        timestamp=timestamp,
    )

    log_text = log_path.read_text(encoding="utf-8")
    assert log_path.name.startswith("anki_deck_builder_run_20240101-120000")
    assert "Status: success" in log_text
    assert "Mode: Vocabulary" in log_text
    assert "Total terms: 10" in log_text
    assert "Notes added: 9" in log_text
    assert "ERROR: missing media file" in log_text
    assert "WARNING: warned about something" in log_text
    assert "console line" in log_text
