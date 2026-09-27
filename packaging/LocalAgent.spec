# Build with: python -m PyInstaller packaging/LocalAgent.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata
root = Path(SPECPATH).parent
a = Analysis([str(root/'packaging/entry.py')], pathex=[str(root)],
    binaries=[], datas=[(str(root/'local_agent/ui'), 'local_agent/ui')] + collect_data_files('ddgs') + copy_metadata('ddgs'),
    hiddenimports=['local_agent.builtin_tools','uvicorn.logging','uvicorn.loops.auto','uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto','uvicorn.lifespan.on', 'webview.platforms.winforms',
        'webview.platforms.edgechromium', 'ddgs.ddgs'] + collect_submodules('ddgs.engines') + collect_submodules('pygments.lexers'),
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['streamlit','pytest','pandas','numpy','matplotlib','PyQt5','PyQt6','PySide2','PySide6','tkinter'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Luma',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(root/'local_agent/ui/luma.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Luma')
