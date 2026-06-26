# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH
SRC = os.path.join(ROOT, "src")
PYZ_CLIENT = os.path.join(
    ROOT, "DotLauncher.exe_extracted", "PYZ.pyz_extracted", "python_max_client"
)

# main.pyc тянет много подмодулей selenium — PyInstaller их не видит статически
SELENIUM_IMPORTS = collect_submodules("selenium")
SELENIUMWIRE_IMPORTS = collect_submodules("seleniumwire")
UC_IMPORTS = collect_submodules("undetected_chromedriver")
STEALTH_IMPORTS = collect_submodules("selenium_stealth")

WEBSOCKETS_IMPORTS = collect_submodules("websockets")

HIDDEN = [
    "pkg_resources",
    "setuptools",
    "PyQt6.QtCore",
    "PyQt6.QtWidgets",
    "PyQt6.QtGui",
    "blinker",
    "fake_useragent",
    "python_socks",
    "socks",
    "OpenSSL",
    "cryptography",
    "seleniumwire_patch",
    "ui_patches",
    "modern_gui",
    "launch_panel",
    "checker_panel",
    "session_token_parse",
    "session_registry",
    "session_reconnect",
    "sessions_meta",
    "proxy_backend",
    "chromedriver_compat",
    "table_ui",
    "app_version",
    "toast_ui",
    "tutorial",
    "theme",
    "manager_guide",
    "update_checker",
    "info_dialog",
    "token_organizer",
    "h11",
    "h2",
    "hyperframe",
    "hpack",
    "kaitaistruct",
    "pyasn1",
    "pyasn1.codec.der.decoder",
    "pydivert",
    "zstandard",
    "tzdata",
]

HIDDEN += (
    SELENIUM_IMPORTS
    + SELENIUMWIRE_IMPORTS
    + UC_IMPORTS
    + STEALTH_IMPORTS
    + WEBSOCKETS_IMPORTS
)

DATAS = [
    (SRC, "src"),
    (PYZ_CLIENT, "python_max_client"),
    (os.path.join(ROOT, "version.json"), "."),
]
DATAS += collect_data_files("selenium")
DATAS += collect_data_files("seleniumwire")
DATAS += collect_data_files("pydivert.windivert_dll")
DATAS += collect_data_files("tzdata")
DATAS += collect_data_files("fake_useragent")
DATAS += collect_data_files("selenium_stealth", include_py_files=True)

a = Analysis(
    ["run_launcher.py"],
    pathex=[ROOT, SRC],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Maxitochka",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Maxitochka",
)
