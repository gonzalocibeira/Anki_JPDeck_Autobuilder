# Anki JP Deck Autobuilder

Anki JP Deck Autobuilder is a command-line utility that assembles a multimedia Anki deck from a list of Japanese terms. Given a CSV file that contains the vocabulary you want to study, the tool enriches each term with readings, glosses, example sentences, native-language definitions, and an illustrative image gathered from public web APIs (Jisho, Tatoeba, Kotobank dictionary, DuckDuckGo image search, and Japanese Wikipedia). The resulting content is packaged into an `.apkg` file that can be imported directly into Anki.

## Features

- **CSV ingestion** – Reads a single-column CSV (any common delimiter) containing Japanese terms.
- **Automated enrichment** – Queries several public APIs (Jisho, Tatoeba, Japanese Wikipedia, Kotobank dictionary, and DuckDuckGo image search) to supplement each term with kana readings, English glosses, example sentences, monolingual definitions, and related imagery.
- **Audio synthesis** – Generates optional Japanese text-to-speech clips for each term using gTTS and bundles them with the deck.
- **Deck append support** – Reuses stored deck/model IDs so newly generated cards merge with an existing deck when imported into Anki.
- **Progress feedback** – Displays a Rich-powered progress bar and build summary in the terminal.
- **Media packaging** – Downloads image assets and bundles them alongside the deck for a ready-to-import `.apkg`.

## Requirements

- Python 3.8 or newer (Python 3.10+ recommended for packaging on macOS).
- Internet access (the script performs live API calls for each term).
- The following Python packages:
  - [`typer[all]`](https://typer.tiangolo.com/)
  - [`rich`](https://rich.readthedocs.io/)
  - [`requests`](https://requests.readthedocs.io/)
  - [`genanki`](https://github.com/kerrickstaley/genanki)
  - [`unidecode`](https://github.com/avian2/unidecode)
  - [`python-slugify`](https://github.com/un33k/python-slugify)
  - [`gTTS`](https://github.com/pndurette/gTTS)
  - [`PyInstaller`](https://pyinstaller.org/) (for building the macOS app bundle)

### Installing dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install typer[all] rich requests genanki unidecode python-slugify gTTS PyInstaller
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
- `media/` – A folder containing any images and synthesized audio clips generated for the cards.
- `anki_deck_builder.config.json` – Stores deck/model identifiers so future runs can append to the same Anki deck.

## How it works (pipeline)

1. **Read terms** – `read_csv_single_column` parses the provided CSV to produce a list of vocabulary items.
2. **Enrich data** (per term):
   - `fetch_jisho` queries the Jisho API for kana readings and English definitions.
   - `fetch_tatoeba_example` retrieves a Japanese example sentence and its English translation from Tatoeba.
- `fetch_wikipedia_ja_definition` retrieves the introductory extract from Japanese Wikipedia and trims filler text for a concise definition. If Wikipedia lacks a result, `fetch_kotobank_ja_definition` falls back to the Kotobank 国語辞典 for a short definition.
   - `fetch_duckduckgo_image` searches DuckDuckGo's image index for a representative image, downloading the first suitable thumbnail. The lookup adapts by trying the original term, its reading, and the leading English glosses until an image is found.
   - `generate_term_audio` synthesizes Japanese text-to-speech (if gTTS is installed) so the resulting notes can play back pronunciation audio inside Anki.
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

### Preventing macOS sleep during long runs

On macOS laptops, the system may automatically go to sleep after a period of inactivity. When that happens, background processes
are paused—interrupting deck builds in progress, halting media downloads, and potentially leaving partially generated output in
your `--output-dir`. To keep the machine awake for the duration of a long run, wrap your command with the built-in `caffeinate`
utility:

```bash
caffeinate -im python anki_deck_builder.py build --csv-path terms.csv
```

- `-i` tells macOS to prevent idle sleep so the CPU keeps working.
- `-m` blocks the system from sleeping while disk activity is happening (useful for download-heavy builds).

This combination keeps the process running while still allowing the display to sleep normally. When the command exits, `caffeinate` automatically releases the sleep prevention. If you prefer the screen to remain lit for visual confirmation, add `-s`; otherwise, you can leave it off and let the display power down.

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
- If the optional gTTS dependency is missing, the script prints a clear installation hint and continues building the deck without audio.
- If no terms are found in the CSV, the script exits without creating an output deck.
- Missing CSV files trigger an error message and exit code 1.

## Limitations

- The tool depends on the uptime and rate limits of third-party APIs (Jisho, Tatoeba, Kotobank dictionary, Japanese Wikipedia, DuckDuckGo image search).
- Only a single card template is provided (front: expression/reading/image, back: English gloss, sentences, definition).
- Definitions and example sentences may not always be available for every term.

## Development & testing

You can see the available Typer commands by running:

```bash
python anki_deck_builder.py --help
```

(Ensure the required dependencies are installed beforehand.)

Contributions and improvements are welcome! Feel free to fork the repository and submit pull requests.

## macOS app packaging (step-by-step)

The repository ships with a Tkinter GUI (`mac_gui_app.py`) and a PyInstaller spec file that builds a native-looking, windowed
`.app` bundle (the spec sets `console=False`, so the GUI opens without a Terminal window). Follow the checklist below from start to finish—no prior packaging experience is required. For an in-depth explanation
of the pipeline—including environment setup notes specific to macOS 26, validation commands, and clean-room testing tips—see
[`docs/macos_build_pipeline.md`](docs/macos_build_pipeline.md).

> **Tip:** All commands assume the Terminal app on macOS. Copy and paste the code blocks exactly as written.

### 1. One-time macOS prerequisites

1. **Update macOS.** Open **System Settings → General → Software Update** and install any pending updates. Reboot if asked.
2. **Install Xcode Command Line Tools.** Run the following command and confirm any prompts:
   ```bash
   xcode-select --install
   ```
3. **Install Homebrew (optional but recommended).** If you do not already have it:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Homebrew simplifies installing Python and other utilities. If you already have an up-to-date Python 3.10+ you can skip this step.

### 2. Prepare a clean workspace

1. **Choose a folder** where you want the project to live (e.g., `~/Projects`).
2. **Open Terminal** and navigate there, replacing the example path if needed:
   ```bash
   cd ~/Projects
   ```
3. **Clone the repository** (or download it as a ZIP and unzip it). Cloning keeps the folder name `Anki_JPDeck_Autobuilder`:
   ```bash
   git clone https://github.com/<your-fork-or-source>/Anki_JPDeck_Autobuilder.git
   cd Anki_JPDeck_Autobuilder
   ```

### 3. Create an isolated Python environment

1. **Ensure Python 3.10 or newer is available (with Tk support).** Verify with:
   ```bash
   python3 --version
   ```
   If the version is older than 3.10, install a newer Python via Homebrew (`brew install python@3.11`) and rerun the command.
   The GUI build depends on the standard-library `tkinter` module, so make sure
   your interpreter bundles it:

   - The [python.org macOS installer](https://www.python.org/downloads/macos/)
     includes Tk by default and is the simplest option.
   - For Homebrew-managed Python, install the matching Tk bindings (replace the
     version suffix if you use a different Python release):

     ```bash
     brew install python-tk@3.11
     ```

   You can confirm Tk support is present with:

   ```bash
   python3 -c "import tkinter; tkinter._test()"
   ```
2. **Create a virtual environment** inside the project folder:
   ```bash
   python3 -m venv .venv
   ```
3. **Activate the environment** (do this in every new Terminal session before running project commands):
   ```bash
   source .venv/bin/activate
   ```
   After activation the prompt will show `(.venv)` at the start—this confirms you are using the isolated environment.

### 4. Install Python dependencies

With the virtual environment active, install every required package—including PyInstaller—using a single pip command:

```bash
pip install --upgrade pip
pip install -r requirements-macos.txt
```

If you prefer to rely on the project’s `Makefile`, you can instead run `make install`, which executes the same installation step.

### 5. Build the macOS app bundle

1. **Double-check you are still inside the virtual environment** (`(.venv)` should be visible in the prompt).
2. **Run the dedicated Make target** that wraps PyInstaller:
   ```bash
   make macos-app
   ```
   The command uses `mac_gui_app.spec` to produce a signed-but-unnotarized app bundle.
3. **Wait for completion.** On success, PyInstaller prints a summary and leaves the finished bundle at:
   ```
   dist/AnkiJPDeckBuilder.app
   ```

### 6. First launch & Gatekeeper prompts

1. In Finder, open the project folder, then open `dist/`.
2. Control-click (`⌃` + click) `AnkiJPDeckBuilder.app` and choose **Open**. macOS Gatekeeper will warn that the app is from an
   unidentified developer.
3. Click **Open** in the dialog. macOS will remember your decision, so you can double-click the app normally next time.

### 6½. Launching from Terminal (for debugging)

If the window appears briefly and then closes, launch the bundled executable from Terminal so you can see any traceback or
missing-resource messages:

```bash
./dist/AnkiJPDeckBuilder.app/Contents/MacOS/AnkiJPDeckBuilder
```

Leave the Terminal window open while testing—the GUI runs inside the same process, so closing the Terminal will terminate the
app. Any runtime errors will print to this Terminal session, which makes it easier to diagnose packaging problems.

### 7. Optional: Create a distributable ZIP

If you want to share the app with others:

```bash
cd dist
zip -r AnkiJPDeckBuilder-macOS.zip AnkiJPDeckBuilder.app
```

The resulting ZIP can be sent to other macOS users. They will need to perform the same Control-click → Open step the first time they launch it.

### Troubleshooting on macOS

- **Gatekeeper warnings:** Because the bundle is unsigned and not notarized, macOS may block the first launch. Right-click the
  app, choose **Open**, and confirm the prompt. Alternatively remove the quarantine attribute manually:
  ```bash
  xattr -d com.apple.quarantine dist/AnkiJPDeckBuilder.app
  ```
- **Codesigning / notarization:** To distribute the app broadly you should sign it with your Apple Developer ID and submit it for
  notarization. PyInstaller's [codesigning docs](https://pyinstaller.org/en/stable/usage.html#macos-codesigning) cover the
  required steps.
- **Missing dependencies:** If the app immediately quits, ensure the virtual environment used for packaging includes all runtime
  dependencies listed above. Rebuild after reinstalling packages or clearing the `build/` and `dist/` directories with `make clean`.
