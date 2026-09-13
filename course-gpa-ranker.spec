# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path(SPEC).resolve().parent


a = Analysis(
    [str(project_dir / "app.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[
        (str(project_dir / "web"), "web"),
        (str(project_dir / "data"), "data"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="course-gpa-ranker-v2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
