# PyInstaller build for Queryon (run from the repo root):  pyinstaller packaging/queryon.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

datas, binaries, hiddenimports = [], [], []
for pkg in ("llama_cpp", "docx", "pptx", "odf", "striprtf"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += [(str(ROOT / "assets"), "assets")]
hiddenimports += ["win32com.client", "pythoncom", "jinja2"]

a = Analysis(
    [str(ROOT / "run_queryon.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "IPython", "pytest", "cv2", "onnxruntime",
              "torch", "sympy", "pymupdf4llm", "pymupdf.layout", "cryptography",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning"],
    noarchive=False,
)
# Drop PyMuPDF's optional layout-analysis models and dev headers (~50 MB, not used).
_skip = ("pymupdf/layout", "pymupdf/mupdf-devel")
a.datas = [d for d in a.datas if not any(x in d[0].replace("\\", "/") for x in _skip)]
a.binaries = [b for b in a.binaries if not any(x in b[0].replace("\\", "/") for x in _skip)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Queryon",
    icon=str(ROOT / "assets" / "queryon.ico"),
    console=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Queryon")
