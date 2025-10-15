# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_tcl_files as _collect_tcl_files
except Exception:  # pragma: no cover - PyInstaller < 6
    _collect_tcl_files = None

try:
    from PyInstaller.utils.hooks import collect_tk_files as _collect_tk_files
except Exception:  # pragma: no cover - PyInstaller < 6
    _collect_tk_files = None


def _legacy_collect_tk_assets():
    """Collect Tcl/Tk resource directories without PyInstaller helpers."""

    datas = []
    seen = set()

    try:
        import tkinter
    except ImportError:  # pragma: no cover - tkinter not installed
        return datas

    tk_interp = tkinter.Tcl()

    def _add_path(path_like, target):
        path = Path(path_like).resolve()
        if not path.exists():
            return
        key = (str(path), target)
        if key in seen:
            return
        datas.append(key)
        seen.add(key)

    try:
        _add_path(tk_interp.eval('info library'), 'tcl')
    except tkinter.TclError:  # pragma: no cover - no library available
        pass

    for var_name in ('tk_library', 'ttk::library'):
        try:
            _add_path(tk_interp.eval(f'set {var_name}'), 'tk')
        except tkinter.TclError:
            continue

    return datas


def collect_tk_files():
    datas = []

    if _collect_tcl_files is not None:
        datas.extend(_collect_tcl_files())
    if _collect_tk_files is not None:
        datas.extend(_collect_tk_files())

    if not datas:
        datas.extend(_legacy_collect_tk_assets())

    # Deduplicate while preserving order.
    unique_datas = []
    seen = set()
    for entry in datas:
        if entry in seen:
            continue
        seen.add(entry)
        unique_datas.append(entry)
    return unique_datas

block_cipher = None

tk_datas = collect_tk_files()


a = Analysis(
    ['mac_gui_app.py'],
    pathex=['.'],
    binaries=[],
    datas=tk_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AnkiJPDeckBuilder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AnkiJPDeckBuilder',
)

app = BUNDLE(
    coll,
    name='AnkiJPDeckBuilder.app',
    icon=None,
    bundle_identifier='com.example.ankijpdeckbuilder',
    info_plist={
        'LSMinimumSystemVersion': '10.13.0',
    },
)
