# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: jeden program AgentDruku.exe (onedir) z trybami service | tray | diagnoza | klucz.
# Program konsolowy — usługa musi dostać Ctrl+C od WinSW przy zatrzymaniu; ikona w zasobniku
# odłącza się od swojej konsoli sama (zasobnik._odlacz_konsole). Budowanie: zbuduj.ps1.
import os

KATALOG_AGENTA = os.path.abspath(os.path.join(SPECPATH, '..'))

a = Analysis(
    [os.path.join(KATALOG_AGENTA, 'agent_druku', '__main__.py')],
    pathex=[KATALOG_AGENTA],
    binaries=[],
    datas=[],
    # Moduły ładowane dopiero w trybach (import w funkcji) i zaplecze pystray dla Windows.
    hiddenimports=[
        'agent_druku.aktualizacja', 'agent_druku.crm', 'agent_druku.drukarki',
        'agent_druku.dziennik', 'agent_druku.konfiguracja', 'agent_druku.lokalne_api',
        'agent_druku.petla', 'agent_druku.push', 'agent_druku.sciezki', 'agent_druku.snmp',
        'agent_druku.zasobnik', 'pystray._win32', 'tkinter', 'tkinter.ttk', 'tkinter.messagebox',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AgentDruku',
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='AgentDruku',
)
