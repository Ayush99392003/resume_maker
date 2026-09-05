"""Test SHA-256 PDF caching in compiler."""

import sys
import time
from pathlib import Path

# Ensure backend directory is in path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from core.compiler import compiler


def test_compiler_sha256_caching():
    """Verify that identical LaTeX code reuses cached PDF."""
    latex = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Cache Test Document 100 Users\n"
        "\\end{document}\n"
    )

    # 1. First compile (cache miss)
    t0 = time.perf_counter()
    pdf1 = compiler.compile(latex)
    duration_miss = time.perf_counter() - t0
    assert pdf1.startswith(b"%PDF")

    # 2. Second compile with exact same LaTeX (cache hit)
    t1 = time.perf_counter()
    pdf2 = compiler.compile(latex)
    duration_hit = time.perf_counter() - t1
    assert pdf2.startswith(b"%PDF")
    assert pdf1 == pdf2

    # Cache hit should be significantly faster (< 50ms)
    assert duration_hit < 0.05
    assert duration_hit < duration_miss

    # 3. Modified LaTeX (cache miss)
    latex_modified = latex.replace("100 Users", "101 Users")
    pdf3 = compiler.compile(latex_modified)
    assert pdf3.startswith(b"%PDF")
    assert pdf3 != pdf1
