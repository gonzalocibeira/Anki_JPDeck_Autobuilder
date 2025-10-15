# macOS App Build & Validation Pipeline

This document explains how to produce a self-contained macOS application bundle for
**Anki JP Deck Builder**, and how to validate that the resulting `.app` will run on a
fresh installation of macOS 26 (Sonoma) without requiring extra runtime
software.

The workflow is based on the repository's `mac_gui_app.spec` PyInstaller
configuration and the `macos-app` Make target. It assumes packaging is performed
on macOS 26 or newer with an Apple-provided Python 3.11+ universal build.

## 1. Environment preparation

1. **Update macOS** to the latest 26.x patch release via *System Settings →
   General → Software Update*.
2. **Install Xcode Command Line Tools** if they are not already present:
   ```bash
   xcode-select --install
   ```
3. **Install a universal2 Python** from python.org (preferred) or Homebrew. The
   runtime embedded by PyInstaller matches the interpreter used for the build,
   so using the universal installer ensures the bundle includes both x86_64 and
   arm64 binaries. The macOS GUI relies on Tk, so make sure the interpreter you
   install ships with Tk bindings:

   - The official [python.org macOS installer](https://www.python.org/downloads/macos/)
     bundles `tkinter` out of the box—no extra steps required.
   - When using Homebrew, add the Tk components explicitly (replace the version
     suffix so it matches the Python you installed):

     ```bash
     brew install python-tk@3.11
     ```

   After installation, confirm Tk support is available before continuing:

   ```bash
   python3 -c "import tkinter; tkinter._test()"
   ```
4. **Create and activate a virtual environment** dedicated to the build:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
5. **Install Python dependencies** inside the virtual environment:
   ```bash
   pip install --upgrade pip
   pip install -r requirements-macos.txt
   ```
   The `requirements-macos.txt` file can be generated with `pip freeze` after a
   successful build to make future runs reproducible.

## 2. Building the application bundle

With the environment active, invoke the repository's Make target:

```bash
make macos-app
```

The Makefile runs:

```bash
python3 -m PyInstaller --clean --noconfirm mac_gui_app.spec
```

Key details from `mac_gui_app.spec`:

- **Bundled entry point:** `mac_gui_app.py`.
- **Windowed build:** `console=False` in the PyInstaller spec disables the
  helper console, so the generated app launches directly into the Tkinter GUI
  without a Terminal window.
- **Tk/Tcl resources:** The spec dynamically collects Tcl/Tk resource
  directories using PyInstaller's built-in helpers. This guarantees that
  `Contents/Resources/lib/tcl8.x` and `.../tk8.x` are copied into the bundle so
  the GUI can run on systems without a preinstalled Python distribution.
- **One-folder app bundle:** The `BUNDLE` target assembles
  `dist/AnkiJPDeckBuilder.app` with the default PyInstaller layout. The Python
  runtime and pure-Python modules live in `Contents/Resources`, while native
  extensions and dylibs are stored under `Contents/MacOS` and
  `Contents/Frameworks`.
- **Minimum OS version:** `LSMinimumSystemVersion` is set to `10.13` for
  `x86_64` and `11.0` for `arm64`. Both thresholds are comfortably below macOS
  26, so the bundle advertises compatibility with Sonoma and newer releases.

PyInstaller writes temporary artifacts to `build/` and emits the finished bundle
inside `dist/`.

## 3. Validating self-contained execution

Perform the following manual checks after each build to guarantee the app does
not depend on global system Python installations or user-specific resources:

1. **Inspect native linkage** to ensure all dylib dependencies resolve inside
   the bundle:
   ```bash
   otool -L dist/AnkiJPDeckBuilder.app/Contents/MacOS/AnkiJPDeckBuilder
   ```
   Every listed path should point to either `/System/Library/...` (Apple system
   frameworks) or to files inside the app's `Contents/` directory. If a path
   references `/usr/local/` or `/Library/Frameworks/Python.framework`, rebuild
   using a universal Python installer and confirm the virtual environment is
   active.
2. **Check for missing frameworks**:
   ```bash
   find dist/AnkiJPDeckBuilder.app -name "*.dylib" -print
   ```
   The presence of `libpython3.x.dylib` and `_tkinter.cpython-...dylib` indicates
   that the Python runtime and Tk bindings were bundled successfully.
3. **Verify Gatekeeper metadata** (unsigned but not quarantined within the
   source tree):
   ```bash
   codesign --verify --deep --strict dist/AnkiJPDeckBuilder.app
   ```
   A warning about the bundle being unsigned is expected; however, the command
   must not report missing code signatures for embedded frameworks.
4. **Run the binary from Terminal** to confirm it starts without relying on
   external environment variables:
   ```bash
   ./dist/AnkiJPDeckBuilder.app/Contents/MacOS/AnkiJPDeckBuilder
   ```
   Launching from Terminal keeps stdout/stderr visible, making it easy to spot
   missing resource errors.

## 4. Testing on a clean macOS 26 install

To guarantee compatibility with a pristine system:

1. **Create a snapshot or virtual machine** using Apple Silicon's Virtualization
   framework or third-party tooling (UTM, VMware Fusion, Parallels). Install a
   fresh copy of macOS 26 without Developer Tools or Homebrew.
2. **Transfer the app bundle** (or a ZIP created with `zip -r`) onto the clean
   system.
3. **Clear quarantine attributes** if the app was downloaded from the internet:
   ```bash
   xattr -d com.apple.quarantine AnkiJPDeckBuilder.app
   ```
4. **Launch the GUI** by control-clicking the app and choosing *Open*. Confirm
   that the interface appears and that basic workflows—selecting a CSV file and
   starting a build—execute without additional configuration.
5. **Monitor network access** to ensure the bundled `requests` and `gTTS`
   modules operate using the packaged certificate bundle (`certifi`). If HTTPS
   requests fail, rebuild to ensure `certifi/cacert.pem` is included; PyInstaller
   normally collects it automatically.

## 5. Optional hardening steps

Although not required for functional testing, the following measures improve the
bundle's readiness for wide distribution:

- **Notarize the app:** Sign the bundle with a Developer ID certificate and
  submit it to Apple for notarization. Update `mac_gui_app.spec` with your
  `codesign_identity` and `entitlements` before rerunning PyInstaller.
- **Automated linting:** Add a CI job that runs `pyinstaller --clean
  --noconfirm --log-level INFO mac_gui_app.spec` followed by `codesign --verify`
  on a macOS runner (GitHub Actions `macos-14`).
- **Runtime smoke test:** Script a short `osascript` that launches the built
  app, waits for the main window, and confirms the process stays alive for at
  least five seconds.

Following the above process ensures that the generated `.app` contains the
required Python runtime, Tk assets, and third-party modules so users on macOS 26
can launch it without installing additional software.
