"""Isolate DLL discovery from the calling shell's unrelated native tools."""
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parent
system=Path(os.environ["SystemRoot"])
os.environ["PATH"]=os.pathsep.join(map(str,[Path(sys.executable).parent,Path(sys.base_prefix),Path(sys.base_prefix)/"DLLs",system/"System32",system]))
os.environ["PYINSTALLER_CONFIG_DIR"]=str(root/".local"/"pyinstaller-cache")
from PyInstaller.__main__ import run

if "--bridge" in sys.argv:
    run(["--clean","--noconfirm","--onedir","--console","--name","AutoSkipBridge","native_host.py"])
else:
    run(["--clean","--noconfirm","--onedir","--windowed","--name","AutoSkip",
         "--collect-all","rapidocr_onnxruntime","--collect-submodules","pywinauto",
         "--collect-submodules","winrt","--collect-binaries","winrt","main.py"])
