# -*- mode: python ; coding: utf-8 -*-

import importlib
import importlib.util
import os
import sysconfig
from pathlib import Path

from PyInstaller.utils import hooks as _pyinstaller_hooks

if hasattr(_pyinstaller_hooks, 'collect_tk_files'):
    collect_tk_files = _pyinstaller_hooks.collect_tk_files
else:

    def collect_tk_files():
        """Collect Tcl/Tk resource folders for older PyInstaller releases."""

        def _add_candidate(path_like: Path, *, descend: bool = True):
            path = Path(path_like).resolve()
            if not path.exists():
                return
            if path.is_file():
                _add_candidate(path.parent, descend=False)
                return
            if path in seen:
                return
            if path.name.lower().startswith(('tcl', 'tk')):
                seen.add(path)
                datas.append((str(path), 'tcl'))
                return
            if descend:
                matched = False
                for child in path.iterdir():
                    if child.is_dir():
                        if child.name.lower().startswith(('tcl', 'tk')):
                            _add_candidate(child, descend=False)
                            matched = True
                if matched:
                    return
            # As a last resort include the directory itself.
            seen.add(path)
            datas.append((str(path), 'tcl'))

        configured_paths = [
            os.environ.get('TCL_LIBRARY'),
            os.environ.get('TK_LIBRARY'),
            sysconfig.get_config_var('TCL_LIBRARY'),
            sysconfig.get_config_var('TK_LIBRARY'),
        ]

        if importlib.util.find_spec('tkinter') is not None:
            tkinter_module = importlib.import_module('tkinter')
            tkinter_dir = Path(tkinter_module.__file__).resolve().parent
            configured_paths.extend(
                [
                    tkinter_dir,
                    tkinter_dir.parent,
                    tkinter_dir / 'tcl',
                    tkinter_dir.parent / 'tcl',
                ]
            )

        configured_paths.append(Path(sysconfig.get_path('stdlib')) / 'tcl')

        seen = set()
        datas = []
        for candidate in configured_paths:
            if not candidate:
                continue
            _add_candidate(candidate)
        return datas

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

app = BUNDLE(
    exe,
    name='AnkiJPDeckBuilder.app',
    icon=None,
    bundle_identifier='com.example.ankijpdeckbuilder',
)
