"""Fetch Overleaf template/project source (zip + assets) into a local folder."""

from __future__ import annotations

import io
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen

_PROJECT_ID = re.compile(
    r"overleaf\.com/(?:project|read)/(?:([a-f0-9]{24})|([a-zA-Z0-9_-]+))",
    re.I,
)
_GALLERY = re.compile(
    r"overleaf\.com/latex/templates/([^/?#]+)/([a-zA-Z0-9]+)",
    re.I,
)
_GITHUB_ZIP = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/?#]+))?",
    re.I,
)

IMPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "imports"

try:
    from core.logging_setup import get_logger
except ImportError:
    from .logging_setup import get_logger

log = get_logger("overleaf")


class OverleafImportError(Exception):
    """Raised when an Overleaf URL cannot be imported."""


@dataclass
class ImportResult:
    latex: str
    source_url: str
    project_dir: Optional[str] = None
    main_tex: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)


def validate_overleaf_url(url: str) -> Tuple[str, str]:
    """
    Normalize and classify URL.
    Returns (kind, normalized_url) where kind is gallery|project|github|raw.
    """
    url = (url or "").strip()
    if not url:
        raise OverleafImportError("Empty URL — paste an Overleaf template or project link.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "overleaf.com" in host:
        if _GALLERY.search(url):
            return "gallery", url.split("?")[0].rstrip("/")
        if _PROJECT_ID.search(url):
            return "project", url.split("?")[0].rstrip("/")
        raise OverleafImportError(
            "Unrecognized Overleaf link. Use a gallery template URL like "
            "https://www.overleaf.com/latex/templates/<name>/<id> "
            "or a project/read link. Private projects need to be shared "
            "publicly or paste the .tex / zip instead."
        )
    if "github.com" in host:
        return "github", url.split("?")[0].rstrip("/")
    raise OverleafImportError(
        "URL must be overleaf.com (template/project) or a GitHub repo of a "
        "LaTeX resume. You can also paste .tex source in the setup form."
    )


def _download(url: str, timeout: int = 45) -> Tuple[bytes, str]:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; ResumeMaker/1.0; +local)"
            ),
            "Accept": "*/*",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        final = resp.geturl()
        data = resp.read()
        return data, final


def _pick_main_tex(paths: List[str]) -> Optional[str]:
    basenames = {Path(p).name.lower(): p for p in paths if p.lower().endswith(".tex")}
    for candidate in ("main.tex", "resume.tex", "cv.tex", "resume_cv.tex"):
        if candidate in basenames:
            return basenames[candidate]
    # Prefer shallowest path with \documentclass — caller may re-check
    tex_paths = [p for p in paths if p.lower().endswith(".tex")]
    tex_paths.sort(key=lambda p: (p.count("/"), len(p)))
    return tex_paths[0] if tex_paths else None


def _read_text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _extract_zip_to_dir(data: bytes, dest: Path) -> List[str]:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Guard zip-slip
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                continue
            zf.extract(info, dest)
        names = [
            n.replace("\\", "/")
            for n in zf.namelist()
            if not n.endswith("/")
        ]
    # If zip has a single top-level folder, keep as-is (paths relative)
    return names


def _flatten_single_root(project_dir: Path) -> Path:
    """If extract created one root folder, return that folder as project root."""
    children = [p for p in project_dir.iterdir() if not p.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return project_dir


def _load_main_from_dir(project_dir: Path) -> Tuple[str, str, List[str]]:
    tex_files = [str(p.relative_to(project_dir)).replace("\\", "/")
                 for p in project_dir.rglob("*.tex")]
    if not tex_files:
        raise OverleafImportError("Downloaded project has no .tex files")
    main_rel = _pick_main_tex(tex_files) or tex_files[0]
    # Prefer file that contains \documentclass
    best = None
    for rel in sorted(tex_files, key=lambda p: (p.count("/"), len(p))):
        text = _read_text((project_dir / rel).read_bytes())
        if "\\documentclass" in text:
            best = (rel, text)
            break
    if best is None:
        text = _read_text((project_dir / main_rel).read_bytes())
        best = (main_rel, text)
    return best[1], best[0], tex_files


def _gallery_candidates(url: str) -> List[str]:
    g = _GALLERY.search(url)
    if not g:
        return [url]
    slug, tid = g.group(1), g.group(2)
    base = f"https://www.overleaf.com/latex/templates/{slug}/{tid}"
    return [
        f"{base}/download",
        f"{base}/raw",
        f"https://www.overleaf.com/project/{tid}/download/zip",
        url,
    ]


def _project_candidates(url: str) -> List[str]:
    m = _PROJECT_ID.search(url)
    cands = []
    if m:
        pid = m.group(1) or m.group(2)
        cands.append(f"https://www.overleaf.com/project/{pid}/download/zip")
        cands.append(f"https://www.overleaf.com/read/{pid}/download/zip")
    cands.append(url)
    return cands


def _github_zip_url(url: str) -> Optional[str]:
    m = _GITHUB_ZIP.search(url)
    if not m:
        return None
    owner, repo, branch = m.group(1), m.group(2).removesuffix(".git"), m.group(3)
    branch = branch or "main"
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"


def _new_import_dir() -> Path:
    IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = IMPORTS_DIR / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _try_html_for_zip_links(html: str, base_url: str) -> List[str]:
    """Pull zip / github / download links from an Overleaf HTML page."""
    found = []
    for m in re.finditer(
        r'href=["\']([^"\']*(?:download|\.zip|github\.com)[^"\']*)["\']',
        html,
        re.I,
    ):
        href = m.group(1)
        abs_url = urljoin(base_url, href)
        if abs_url not in found:
            found.append(abs_url)
    for m in re.finditer(
        r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',
        html,
    ):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found


def import_overleaf_url(url: str) -> ImportResult:
    """
    Download Overleaf/GitHub template into data/imports/<id>/ and return
    main LaTeX + project_dir for asset-aware compile.
    """
    kind, normalized = validate_overleaf_url(url)
    log.info("import start kind=%s url=%s", kind, normalized)
    warnings: List[str] = []
    candidates: List[str] = []

    if kind == "gallery":
        candidates = _gallery_candidates(normalized)
    elif kind == "project":
        candidates = _project_candidates(normalized)
    elif kind == "github":
        zip_url = _github_zip_url(normalized)
        if zip_url:
            candidates.append(zip_url)
        candidates.append(normalized)
    else:
        candidates = [normalized]

    last_err: Optional[Exception] = None
    html_follow: List[str] = []

    for cand in candidates + html_follow:
        log.debug("try download %s", cand)
        try:
            data, final = _download(cand)
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            last_err = e
            log.debug("download failed %s: %s", cand, e)
            continue

        # Zip package
        if data[:2] == b"PK":
            dest = _new_import_dir()
            try:
                _extract_zip_to_dir(data, dest)
                root = _flatten_single_root(dest)
                latex, main_tex, files = _load_main_from_dir(root)
                log.info(
                    "import zip ok main=%s files=%s dir=%s",
                    main_tex,
                    len(files),
                    root,
                )
                return ImportResult(
                    latex=latex,
                    source_url=final,
                    project_dir=str(root.resolve()),
                    main_tex=main_tex,
                    warnings=warnings,
                    files=files,
                )
            except Exception as e:
                shutil.rmtree(dest, ignore_errors=True)
                last_err = e
                log.warning("zip extract failed: %s", e)
                continue

        text = _read_text(data)
        if "\\documentclass" in text:
            # Single tex file — still stage into a project dir
            dest = _new_import_dir()
            main_path = dest / "main.tex"
            main_path.write_text(text, encoding="utf-8")
            return ImportResult(
                latex=text,
                source_url=final,
                project_dir=str(dest.resolve()),
                main_tex="main.tex",
                warnings=warnings,
                files=["main.tex"],
            )

        # HTML page — discover more download links once
        if ("<html" in text.lower() or "overleaf" in text.lower()) and not html_follow:
            html_follow = _try_html_for_zip_links(text, final)[:12]
            for extra in html_follow:
                if extra not in candidates:
                    candidates.append(extra)
            # GitHub repos discovered from page
            for link in list(html_follow):
                gz = _github_zip_url(link)
                if gz and gz not in candidates:
                    candidates.append(gz)
            last_err = OverleafImportError(
                "Got HTML page; trying linked zip/GitHub downloads…"
            )
            continue

        last_err = OverleafImportError(
            "Downloaded content is not a .tex or zip"
        )

    log.error(
        "import.error: all candidates failed last=%s tried=%s",
        last_err,
        len(candidates) + len(html_follow),
    )
    raise OverleafImportError(
        "Could not download template from that link. "
        "Use a public Overleaf gallery URL "
        "(https://www.overleaf.com/latex/templates/…), "
        "a public project download, or paste the .tex / upload zip. "
        f"Last error: {last_err}"
    )


# Back-compat helper used by older call sites expecting a tuple
def import_overleaf_url_legacy(url: str) -> Tuple[str, str]:
    result = import_overleaf_url(url)
    return result.latex, result.source_url
