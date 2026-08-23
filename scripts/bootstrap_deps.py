"""沙盒友善的依賴引導器:純 stdlib 下載 PyPI 輪檔並解壓到 ./deps
(避開 pip 在受限環境下的臨時目錄限制)

用法: python scripts/bootstrap_deps.py [--core]
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".deps"
TMP = ROOT / ".tmp"

# 核心閉包(不含 yfinance / futu-api,可選套件由用戶在自己環境以 pip 安裝)
CORE = [
    # 直依賴
    "numpy", "pandas", "python-dateutil", "pyyaml", "requests", "tzdata",
    "pytz",
    "fastapi", "starlette", "pydantic", "uvicorn", "anyio", "sniffio",
    "typing-extensions", "annotated-types",
    # 間接依賴(固定閉包,免解析器)
    "six", "urllib3", "idna", "certifi", "charset-normalizer",
    "click", "h11", "pydantic-core", "typing-inspection", "annotated-doc",
]

PYVER = f"cp{sys.version_info.major}{sys.version_info.minor}"


def pick(urls: list[dict]) -> dict:
    """優先 cpNNN-win_amd64,其次 abi3,最後 pure python3 wheel。"""
    def score(u: dict) -> int:
        fn = u["filename"]
        if not fn.endswith(".whl"):
            return -1
        py_tag, abi_tag, plat_tag = fn[:-4].split("-")[-3:]
        s = -1
        if plat_tag == "win_amd64":
            if py_tag == PYVER and abi_tag == PYVER:
                s = 100
            elif abi_tag.endswith("abi3"):
                s = 80
        elif plat_tag == "any" and py_tag in ("py3", "py2.py3", PYVER) and abi_tag == "none":
            s = 50
        return s
    ranked = sorted((u for u in urls if score(u) > 0),
                    key=score, reverse=True)
    return ranked[0] if ranked else None


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "bootstrap-deps/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main() -> int:
    DEST.mkdir(exist_ok=True)
    TMP.mkdir(exist_ok=True)
    failed = []
    for i, name in enumerate(CORE, 1):
        try:
            meta = json.loads(fetch(f"https://pypi.org/pypi/{name}/json"))
            ver = meta["info"]["version"]
            wheel = pick(meta["urls"])
            if wheel is None:
                failed.append(f"{name}: 無相容 wheel({' '.join(u['filename'] for u in meta['urls'][:6])})")
                continue
            print(f"[{i:>2}/{len(CORE)}] {name}=={ver} ← {wheel['filename']}")
            blob = fetch(wheel["url"])
            zpath = TMP / wheel["filename"]
            zpath.write_bytes(blob)
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(DEST)
            zpath.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}: {type(e).__name__}: {e}")
    print("-" * 56)
    if failed:
        print("失敗:")
        for f in failed:
            print("  ❌", f)
        return 1
    print(f"✅ {len(CORE)} 個套件已安裝到 {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
