"""POST /setup/import with crashy Harshibar-like paste; expect PDF + compat_notes."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
COMPAT = BACKEND / "data" / "imports" / "harshibar_render" / "resume_compat.tex"

CRASHY = r"""
\usepackage{fontawesome5}
\usepackage[Scale=0.85]{FiraMono}
\usepackage{contour}
"""


def main() -> None:
    compat = COMPAT.read_text(encoding="utf-8")
    raw = compat.replace(
        r"\usepackage[normalem]{ulem}",
        r"\usepackage[normalem]{ulem}" + "\n" + CRASHY,
        1,
    )
    raw = raw.replace("Tel", r"\faPhone*", 1)
    body = json.dumps({"latex": raw}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/setup/import",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    print("compat_notes:", data.get("compat_notes"))
    print("compile_error:", data.get("compile_error"))
    print("has_pdf:", bool(data.get("pdf_base64")))
    assert data.get("compat_notes"), "expected compat_notes"
    assert data.get("pdf_base64"), data.get("compile_error")
    print("API_OK")


if __name__ == "__main__":
    main()
