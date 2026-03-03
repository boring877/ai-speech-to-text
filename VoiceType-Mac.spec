# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Collect all dependencies
keyboard_datas, keyboard_binaries, keyboard_hiddenimports = collect_all('keyboard')
pyperclip_datas, pyperclip_binaries, pyperclip_hiddenimports = collect_all('pyperclip')
pystray_datas, pystray_binaries, pystray_hiddenimports = collect_all('pystray')
pyaudio_datas, pyaudio_binaries, pyaudio_hiddenimports = collect_all('pyaudio')

a = Analysis(
    ['voice_type.py'],
    pathex=[],
    binaries=keyboard_binaries + pyperclip_binaries + pystray_binaries + pyaudio_binaries,
    datas=keyboard_datas + pyperclip_datas + pystray_datas + pyaudio_datas,
    hiddenimports=keyboard_hiddenimports + pyperclip_hiddenimports + pystray_hiddenimports + pyaudio_hiddenimports + ['httpx', 'PIL', 'pyperclip'],
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
    a.binaries,
    a.datas,
    [],
    name='VoiceType',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Create a macOS app bundle
app = BUNDLE(
    exe,
    name='VoiceType.app',
    icon=None,
    bundle_identifier='com.voicetype.app',
    info_plist={
        'NSMicrophoneUsageDescription': 'Voice Type needs access to your microphone for speech-to-text functionality.',
        'LSBackgroundOnly': False,
        'LSUIElement': True,  # Hide from dock, show in menu bar
    },
)