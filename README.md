# Anki JP Deck Autobuilder

Anki JP Deck Autobuilder is a command-line utility that assembles a multimedia Anki deck from a list of Japanese terms. Given a CSV file that contains the vocabulary you want to study, the tool enriches each term with readings, glosses, example sentences, native-language definitions, and an illustrative image gathered from public web APIs (Jisho, Tatoeba, Goo dictionary, Wikimedia Commons, and Japanese Wikipedia). The resulting content is packaged into an `.apkg` file that can be imported directly into Anki.

## Features

- **CSV ingestion** – Reads a single-column CSV (any common delimiter) containing Japanese terms.
- **Automated enrichment** – Queries several public APIs (Jisho, Tatoeba, Goo dictionary, Wikimedia Commons, and Japanese Wikipedia) to supplement each term with kana readings, English glosses, example sentences, monolingual definitions, and related imagery.
- **Deck append support** – Reuses stored deck/model IDs so newly generated cards merge with an existing deck when imported into Anki.
- **Progress feedback** – Displays a Rich-powered progress bar and build summary in the terminal.
- **Media packaging** – Downloads image assets and bundles them alongside the deck for a ready-to-import `.apkg`.

## Requirements

- Python 3.8 or newer.
- Internet access (the script performs live API calls for each term).
- The following Python packages:
  - [`typer[all]`](https://typer.tiangolo.com/)
  - [`rich`](https://rich.readthedocs.io/)
  - [`requests`](https://requests.readthedocs.io/)
  - [`genanki`](https://github.com/kerrickstaley/genanki)
  - [`unidecode`](https://github.com/avian2/unidecode)
  - [`python-slugify`](https://github.com/un33k/python-slugify)

### Installing dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install typer[all] rich requests genanki unidecode python-slugify
```

## Input expectations

The script expects a CSV file where each row contains a Japanese term in the first non-empty cell. Common delimiters (comma, tab, semicolon) are auto-detected. Whitespace-only rows are ignored. Example `terms.csv`:

```csv
猫
犬
食べる
```

## Output overview

Running the tool produces the following artifacts inside the chosen output directory (default: `./out`):

- `Japanese_Auto_Deck.apkg` – The packaged Anki deck file.
- `media/` – A folder containing any images downloaded for the cards.
- `anki_deck_builder.config.json` – Stores deck/model identifiers so future runs can append to the same Anki deck.

## How it works (pipeline)

1. **Read terms** – `read_csv_single_column` parses the provided CSV to produce a list of vocabulary items.
2. **Enrich data** (per term):
   - `fetch_jisho` queries the Jisho API for kana readings and English definitions.
   - `fetch_tatoeba_example` retrieves a Japanese example sentence and its English translation from Tatoeba.
   - `fetch_goo_ja_definition` fetches a concise Japanese definition from the Goo 国語 dictionary (trying both direct entry pages and site-wide search). If Goo lacks a result, `fetch_wikipedia_ja_definition` falls back to Japanese Wikipedia for a short extract.
   - `fetch_commons_image` searches Wikimedia Commons for a representative image, downloading the first suitable thumbnail. The lookup adapts by trying the original term, its reading, and the leading English glosses until an image is found.
3. **Assemble card data** – The collected fields are wrapped in a `CardData` dataclass, which formats the Anki note fields (including an `<img>` tag when an image is available).
4. **Configure deck** – If `--new-deck` is enabled (default), fresh deck/model IDs are generated and persisted to `anki_deck_builder.config.json`. Otherwise, existing IDs are loaded so new notes merge with an existing deck on import.
5. **Build notes** – The script iterates over the enriched cards, creating `genanki.Note` instances using a predefined model that renders the front/back layout.
6. **Package deck** – `genanki.Package` writes the `.apkg` file while bundling downloaded media assets.
7. **Summarize results** – A table is printed summarizing terms processed, notes added, media count, and the location of the output files.

## Usage

Invoke the script via Python (after installing dependencies):

```bash
python anki_deck_builder.py build --csv-path terms.csv
```

When executed, Typer will prompt for any missing options. The command supports the following flags:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `--csv-path PATH` | Path to the input CSV file (required). | _Prompted_ |
| `--output-dir PATH` | Directory where the deck, media, and config files are stored. | `./out` |
| `--new-deck / --no-new-deck` | Whether to create a new deck (new IDs) or reuse stored IDs to append to an existing deck. | `--new-deck` |
| `--deck-name TEXT` | Name of the generated Anki deck. When appending with stored IDs and the default name, the saved deck name is reused. | `Japanese Auto Deck` |
| `--config PATH` | Path to a JSON file containing `deck_id`, `model_id`, and `deck_name`. Useful for managing multiple deck configurations. | `output_dir/anki_deck_builder.config.json` |

### Example workflow

1. Prepare your vocabulary list in `terms.csv`.
2. Run the builder:
   ```bash
   python anki_deck_builder.py build --csv-path terms.csv --output-dir ./anki_out --deck-name "JLPT N5"
   ```
3. Import the generated `.apkg` (e.g., `anki_out/JLPT_N5.apkg`) into Anki. If you rerun the script with `--no-new-deck` and the same config file, new cards append seamlessly to the existing deck.

## Configuration details

The config file is a simple JSON document that stores identifiers used by Anki to recognize decks and note models. Example:

```json
{
  "deck_id": 123456789,
  "model_id": 987654321,
  "deck_name": "JLPT N5"
}
```

- Delete this file or pass `--new-deck` to generate fresh IDs.
- Reuse the same file with `--no-new-deck` to continue adding cards to a previously created deck.

## Error handling & logging

- API failures are logged to the console in yellow and gracefully skipped, so the build continues with whatever data was retrieved.
- If no terms are found in the CSV, the script exits without creating an output deck.
- Missing CSV files trigger an error message and exit code 1.

## Limitations

- The tool depends on the uptime and rate limits of third-party APIs (Jisho, Tatoeba, Goo dictionary, Japanese Wikipedia, Wikimedia Commons).
- Only a single card template is provided (front: expression/reading/image, back: English gloss, sentences, definition).
- Definitions and example sentences may not always be available for every term.

## Development & testing

You can see the available Typer commands by running:

```bash
python anki_deck_builder.py --help
```

(Ensure the required dependencies are installed beforehand.)

Contributions and improvements are welcome! Feel free to fork the repository and submit pull requests.
