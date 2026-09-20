"""LaTeX compatibility, error classification, and targeted repair engine.

Provides automatic fallback chains for missing fonts (XeTeX/Tectonic fontspec),
undefined colors (xcolor), missing side-files/packages, math packages,
table packages, undefined citations, and missing figures without requiring
destructive full-document LLM rewrites.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from core.logging_setup import get_logger
except ImportError:
    from .logging_setup import get_logger

log = get_logger("latex_compatibility")

# ---------------------------------------------------------------------------
# Handlers: Font Fallback Chain
# ---------------------------------------------------------------------------

SERIF_FALLBACK = "TeX Gyre Termes"
SANS_FALLBACK = "TeX Gyre Heros"
MONO_FALLBACK = "TeX Gyre Cursor"
DEFAULT_FALLBACK = "TeX Gyre Termes"

# Regexes to capture font declarations in .tex and .cls files
_FONT_CMD_RE = re.compile(
    r"(\\(?:setmainfont|setsansfont|setmonofont|newfontfamily|"
    r"newfontface|fontspec)(?:\s*\[[^\]]*\])?)\s*\{([^}]+)\}"
)

_FONTSPEC_ERR_RE = re.compile(
    r'(?:Package fontspec Error|fontspec error):\s*The font\s*["\']'
    r'([^"\']+)["\']\s*cannot be found',
    re.IGNORECASE,
)

_XCOLOR_ERR_RE = re.compile(
    r"(?:Package xcolor Error:\s+)?Undefined color\s*[`']([^`']+)['`]",
    re.IGNORECASE,
)

_FILE_NOT_FOUND_RE = re.compile(
    r"(?:! LaTeX Error:\s+)?File\s*[`']([^`']+)['`]\s*not found",
    re.IGNORECASE,
)

_IMG_FILE_RE = re.compile(
    r"(?:! LaTeX Error:\s+File\s*[`']([^`']+\.(?:png|jpg|jpeg|pdf|eps|svg))"
    r"['`]\s*not found|"
    r"Package pdftex\.def Error:\s*File\s*[`']"
    r"([^`']+\.(?:png|jpg|jpeg|pdf|eps|svg))['`]\s*not found|"
    r"File\s*[`']([^`']+\.(?:png|jpg|jpeg|pdf|eps|svg))['`]\s*not found)",
    re.IGNORECASE,
)

_MATH_CMD_RE = re.compile(
    r"Undefined control sequence\.\s*l\.\d+\s*\\("
    r"align|text|mathbb|mathcal|boldsymbol|coloneqq|"
    r"DeclareMathOperator|bm|pmatrix|bmatrix|vmatrix|Vmatrix|cases|"
    r"eqref|iint|iiint|dddot|ddddot|overbrace|underbrace|dfrac|tfrac|"
    r"substack|intertext|shortintertext|mathclap|mathrlap|mathllap"
    r")\b",
    re.IGNORECASE,
)

_TABLE_CMD_RE = re.compile(
    r"Undefined control sequence\.\s*l\.\d+\s*\\("
    r"toprule|midrule|bottomrule|cmidrule|specialrule|"
    r"addlinespace|multirow"
    r")\b",
    re.IGNORECASE,
)

_CITATION_WARN_RE = re.compile(
    r"(?:Citation\s*[`']([^`']+)['`]\s*on page\s*\d+\s*undefined|"
    r"Package natbib Warning:\s*Citation\s*[`']([^`']+)['`])",
    re.IGNORECASE,
)


def _classify_font_type(font_name: str, cmd_prefix: str = "") -> str:
    """Infer serif, sans, or mono from font name or command."""
    low_cmd = cmd_prefix.lower()
    low_name = font_name.lower()
    if "sans" in low_cmd or any(
        k in low_name
        for k in (
            "sans",
            "helvetica",
            "arial",
            "montserrat",
            "roboto",
            "lato",
        )
    ):
        return SANS_FALLBACK
    if "mono" in low_cmd or any(
        k in low_name
        for k in (
            "mono",
            "code",
            "courier",
            "fira",
            "consolas",
            "typewriter",
        )
    ):
        return MONO_FALLBACK
    return SERIF_FALLBACK


class FontHandler:
    """Resolves and substitutes unavailable fonts with TeX Gyre fonts."""

    @staticmethod
    def extract_missing_font(log_text: str) -> str | None:
        """Extract missing font name from Tectonic/fontspec error logs."""
        match = _FONTSPEC_ERR_RE.search(log_text)
        if match:
            return match.group(1).strip()
        alt = re.search(
            r'font\s+["\']([^"\']+)["\']\s+cannot be found',
            log_text,
            re.IGNORECASE,
        )
        if alt:
            return alt.group(1).strip()
        return None

    @classmethod
    def repair_missing_font(
        cls,
        source: str,
        missing_font: str,
    ) -> tuple[str, dict[str, str] | None]:
        """Replace references to missing_font with TeX Gyre fallback."""
        if not missing_font:
            return source, None

        escaped = re.escape(missing_font)
        base_name = re.sub(
            r"-(?:Regular|Bold|Italic|Light|Medium)",
            "",
            missing_font,
            flags=re.IGNORECASE,
        )
        fallback = _classify_font_type(missing_font)

        replaced = False

        def _sub_font(m: re.Match) -> str:
            nonlocal replaced
            cmd_prefix = m.group(1)
            f_name = m.group(2).strip()
            if (
                f_name == missing_font
                or f_name == base_name
                or missing_font in f_name
                or base_name in f_name
            ):
                chosen_fallback = _classify_font_type(f_name, cmd_prefix)
                replaced = True
                return f"{cmd_prefix}{{{chosen_fallback}}}"
            return m.group(0)

        new_src = _FONT_CMD_RE.sub(_sub_font, source)

        if not replaced:
            pat = re.compile(r"\{[ \t]*" + escaped + r"[ \t]*\}")
            if pat.search(new_src):
                new_src = pat.sub(f"{{{fallback}}}", new_src)
                replaced = True
            elif base_name != missing_font:
                pat_base = re.compile(
                    r"\{[ \t]*" + re.escape(base_name) + r"[ \t]*\}"
                )
                if pat_base.search(new_src):
                    new_src = pat_base.sub(f"{{{fallback}}}", new_src)
                    replaced = True

        if replaced:
            log.info(
                "font_handler.repair: replaced %s with %s",
                missing_font,
                fallback,
            )
            return new_src, {
                "type": "font",
                "original": missing_font,
                "replacement": fallback,
            }

        return new_src, None


# ---------------------------------------------------------------------------
# Handlers: Color Compatibility & Fallback
# ---------------------------------------------------------------------------


class ColorHandler:
    """Detects missing colors and injects safe definitions."""

    @staticmethod
    def extract_missing_color(log_text: str) -> str | None:
        """Extract undefined color name from xcolor logs."""
        match = _XCOLOR_ERR_RE.search(log_text)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def define_missing_color(
        cls,
        source: str,
        color_name: str,
    ) -> tuple[str, dict[str, str] | None]:
        """Inject fallback definition for missing color into preamble."""
        if not color_name:
            return source, None

        # Check if color is already defined
        if re.search(
            r"\\(?:definecolor|providecolor)\{"
            + re.escape(color_name)
            + r"\}",
            source,
        ):
            return source, None

        # Check if color_name is a hex string (#RRGGBB or RRGGBB)
        hex_clean = color_name.lstrip("#").strip()
        is_hex6 = len(hex_clean) == 6 and all(
            c in "0123456789abcdefABCDEF" for c in hex_clean
        )
        is_hex3 = len(hex_clean) == 3 and all(
            c in "0123456789abcdefABCDEF" for c in hex_clean
        )

        if is_hex6:
            r = int(hex_clean[0:2], 16)
            g = int(hex_clean[2:4], 16)
            b = int(hex_clean[4:6], 16)
            rgb = f"{r},{g},{b}"
        elif is_hex3:
            r = int(hex_clean[0] * 2, 16)
            g = int(hex_clean[1] * 2, 16)
            b = int(hex_clean[2] * 2, 16)
            rgb = f"{r},{g},{b}"
        else:
            low = color_name.lower()
            if any(k in low for k in ("blue", "navy", "royal", "primary")):
                rgb = "37,99,235"
            elif any(k in low for k in ("red", "ruby", "maroon", "danger")):
                rgb = "185,28,28"
            elif any(k in low for k in ("green", "forest", "emerald")):
                rgb = "22,101,52"
            elif any(k in low for k in ("gold", "yellow", "orange")):
                rgb = "217,119,6"
            else:
                rgb = "75,85,99"

        def_stmt = f"\\providecolor{{{color_name}}}{{RGB}}{{{rgb}}}\n"

        # Ensure \usepackage{xcolor} is present in source
        if not re.search(r"\\usepackage(?:\[[^\]]*\])?\{xcolor\}", source):
            xc_stmt = "\\usepackage[dvipsnames,svgnames,x11names]{xcolor}\n"
            def_stmt = xc_stmt + def_stmt

        # Insert right before \begin{document} or at top of preamble
        doc_match = re.search(r"\\begin\{document\}", source)
        if doc_match:
            idx = doc_match.start()
            new_src = source[:idx] + def_stmt + source[idx:]
        else:
            new_src = def_stmt + source

        log.info(
            "color_handler.repair: defined color '%s' with RGB {%s}",
            color_name,
            rgb,
        )
        return new_src, {
            "type": "color",
            "original": color_name,
            "action": f"defined fallback RGB {rgb}",
        }


# ---------------------------------------------------------------------------
# Handlers: Math Packages
# ---------------------------------------------------------------------------


class MathHandler:
    """Detects missing math packages and injects amsmath/amssymb/mathtools."""

    @staticmethod
    def is_math_error(log_text: str) -> bool:
        if not log_text:
            return False
        if any(
            pkg in log_text for pkg in ("amsmath", "amssymb", "mathtools")
        ):
            return True
        return bool(_MATH_CMD_RE.search(log_text))

    @classmethod
    def inject_math_packages(
        cls, source: str
    ) -> tuple[str, dict[str, str] | None]:
        pkgs_to_add: list[str] = []
        for pkg in ("amsmath", "amssymb", "mathtools"):
            if not re.search(
                rf"\\usepackage(?:\[[^\]]*\])?\{{{pkg}\}}", source
            ):
                pkgs_to_add.append(pkg)

        if not pkgs_to_add:
            return source, None

        pkg_stmt = f"\\usepackage{{{','.join(pkgs_to_add)}}}\n"
        doc_match = re.search(r"\\begin\{document\}", source)
        if doc_match:
            idx = doc_match.start()
            new_src = source[:idx] + pkg_stmt + source[idx:]
        else:
            new_src = pkg_stmt + source

        log.info("math_handler.repair: injected packages %s", pkgs_to_add)
        return new_src, {
            "type": "math",
            "action": f"injected \\usepackage{{{','.join(pkgs_to_add)}}}",
        }


# ---------------------------------------------------------------------------
# Handlers: Table Packages
# ---------------------------------------------------------------------------


class TableHandler:
    """Detects missing table packages and injects booktabs/multirow."""

    @staticmethod
    def is_table_error(log_text: str) -> bool:
        if not log_text:
            return False
        if "booktabs" in log_text or "multirow" in log_text:
            return True
        return bool(_TABLE_CMD_RE.search(log_text))

    @classmethod
    def inject_table_packages(
        cls, source: str
    ) -> tuple[str, dict[str, str] | None]:
        pkgs_to_add: list[str] = []
        for pkg in ("booktabs", "multirow"):
            if not re.search(
                rf"\\usepackage(?:\[[^\]]*\])?\{{{pkg}\}}", source
            ):
                pkgs_to_add.append(pkg)

        if not pkgs_to_add:
            return source, None

        pkg_stmt = f"\\usepackage{{{','.join(pkgs_to_add)}}}\n"
        doc_match = re.search(r"\\begin\{document\}", source)
        if doc_match:
            idx = doc_match.start()
            new_src = source[:idx] + pkg_stmt + source[idx:]
        else:
            new_src = pkg_stmt + source

        log.info("table_handler.repair: injected packages %s", pkgs_to_add)
        return new_src, {
            "type": "table",
            "action": f"injected \\usepackage{{{','.join(pkgs_to_add)}}}",
        }


# ---------------------------------------------------------------------------
# Handlers: Citations
# ---------------------------------------------------------------------------


class CitationHandler:
    """Detects missing citations and auto-inserts placeholder bibitems."""

    @staticmethod
    def extract_missing_citation(log_text: str) -> str | None:
        m = _CITATION_WARN_RE.search(log_text)
        if m:
            return (m.group(1) or m.group(2) or "").strip()
        m2 = re.search(r"Citation\s*[`']([^`']+)['`]", log_text, re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
        return None

    @classmethod
    def insert_placeholder_bibitem(
        cls, source: str, key: str
    ) -> tuple[str, dict[str, str] | None]:
        if not key:
            return source, None

        if re.search(
            rf"\\bibitem(?:\[[^\]]*\])?\{{{re.escape(key)}\}}", source
        ):
            return source, None

        bibitem_entry = f"\\bibitem{{{key}}} [Reference for {key}].\n"

        bib_match = re.search(r"\\begin\{thebibliography\}\{[^}]*\}", source)
        if bib_match:
            idx = bib_match.end()
            new_src = source[:idx] + "\n" + bibitem_entry + source[idx:]
        else:
            bib_env = (
                "\n\\begin{thebibliography}{99}\n"
                f"{bibitem_entry}"
                "\\end{thebibliography}\n"
            )
            doc_end = re.search(r"\\end\{document\}", source)
            if doc_end:
                idx = doc_end.start()
                new_src = source[:idx] + bib_env + source[idx:]
            else:
                new_src = source + bib_env

        log.info("citation_handler.repair: inserted bibitem for %s", key)
        return new_src, {
            "type": "citation",
            "original": key,
            "action": f"inserted \\bibitem{{{key}}}",
        }


# ---------------------------------------------------------------------------
# Handlers: Figures
# ---------------------------------------------------------------------------


class FigureHandler:
    """Detects missing figure files and substitutes boxed placeholders."""

    @staticmethod
    def extract_missing_figure(log_text: str) -> str | None:
        m = _IMG_FILE_RE.search(log_text)
        if m:
            for g in m.groups():
                if g:
                    return g.strip()
        return None

    @classmethod
    def substitute_figure(
        cls, source: str, missing_file: str, compile_dir: Path | None = None
    ) -> tuple[str, dict[str, str] | None]:
        if not missing_file:
            return source, None

        stem = Path(missing_file).stem
        pat = re.compile(
            r"\\includegraphics(?:\s*\[[^\]]*\])?\s*\{[ \t]*"
            + re.escape(missing_file)
            + r"[ \t]*\}|"
            r"\\includegraphics(?:\s*\[[^\]]*\])?\s*\{[ \t]*"
            + re.escape(stem)
            + r"[ \t]*\}",
            re.IGNORECASE,
        )

        placeholder = (
            f"\\fbox{{\\parbox{{0.8\\linewidth}}{{\\centering "
            f"[Figure placeholder: {Path(missing_file).name}]}}}}"
        )
        new_src, count = pat.subn(lambda _m: placeholder, source)
        if count > 0:
            log.info(
                "figure_handler.repair: substituted \\includegraphics{%s}",
                missing_file,
            )
            return new_src, {
                "type": "figure",
                "original": missing_file,
                "action": "substituted with boxed placeholder",
            }

        return source, None


# ---------------------------------------------------------------------------
# Handlers: File & Package Compatibility
# ---------------------------------------------------------------------------


class PackageHandler:
    """Handles missing side-files or missing packages in compile directory."""

    @staticmethod
    def extract_missing_file(log_text: str) -> str | None:
        """Extract missing filename from Tectonic error logs."""
        match = _FILE_NOT_FOUND_RE.search(log_text)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def repair_missing_file(
        cls,
        source: str,
        missing_file: str,
        compile_dir: Path | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        """Neutralize orphaned \\input{missing} references or touch dummies."""
        if not missing_file:
            return source, None

        stem = Path(missing_file).stem
        ext = Path(missing_file).suffix

        pat = re.compile(
            r"^[ \t]*\\input\{[ \t]*"
            + re.escape(stem)
            + r"(?:\.tex)?[ \t]*\}[ \t]*%?.*$",
            re.MULTILINE,
        )
        repl_msg = (
            f"% [auto-repair: removed missing \\input{{{missing_file}}}]"
        )
        new_src, count = pat.subn(lambda _m: repl_msg, source)

        if count > 0:
            log.info(
                "package_handler.repair: commented missing \\input{%s}",
                missing_file,
            )
            return new_src, {
                "type": "package_or_file",
                "original": missing_file,
                "action": "commented missing \\input",
            }

        if compile_dir and compile_dir.is_dir() and ext in (
            ".tex", ".def", ".cfg"
        ):
            target_path = compile_dir / missing_file
            if not target_path.exists():
                try:
                    target_path.write_text(
                        "% Empty placeholder created by auto-repair\n",
                        encoding="utf-8",
                    )
                    log.info(
                        "package_handler.repair: seeded dummy for %s",
                        missing_file,
                    )
                    return source, {
                        "type": "package_or_file",
                        "original": missing_file,
                        "action": "seeded empty dummy file",
                    }
                except OSError as err:
                    log.warning(
                        "could not write dummy %s: %s", missing_file, err
                    )

        return source, None


# ---------------------------------------------------------------------------
# Error Classifier
# ---------------------------------------------------------------------------


class ErrorClassifier:
    """Categorizes Tectonic logs into actionable repair categories."""

    @staticmethod
    def classify(log_text: str) -> str:
        """Return repair category for given log."""
        if not log_text:
            return "unknown"

        if (
            "fontspec Error" in log_text
            or "fontspec error" in log_text
            or "cannot be found" in log_text
        ):
            return "font"

        if "Undefined color" in log_text or "Package xcolor Error" in log_text:
            return "color"

        if FigureHandler.extract_missing_figure(log_text):
            return "figure"

        if (
            ("File `" in log_text or "File '" in log_text)
            and "not found" in log_text
        ):
            return "package_or_file"

        if MathHandler.is_math_error(log_text):
            return "math"

        if TableHandler.is_table_error(log_text):
            return "table"

        if CitationHandler.extract_missing_citation(log_text):
            return "citation"

        if "Undefined control sequence" in log_text:
            return "command"

        return "unknown"


# ---------------------------------------------------------------------------
# Repair Engine Loop
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS = 5


class RepairEngine:
    """Coordinates targeted deterministic auto-repair loops without LLM."""

    def __init__(self, compiler_instance: Any):
        self.compiler = compiler_instance

    def repair_source_and_workspace(
        self,
        source: str,
        log_text: str,
        compile_dir: Path | None = None,
    ) -> tuple[str, dict[str, str] | None]:
        """Inspect error logs and apply targeted deterministic repairs."""
        category = ErrorClassifier.classify(log_text)

        # 1. Font Error
        if category == "font":
            missing_font = FontHandler.extract_missing_font(log_text)
            if missing_font:
                if compile_dir and compile_dir.is_dir():
                    for cls_file in compile_dir.glob("*.cls"):
                        try:
                            cls_content = cls_file.read_text(
                                encoding="utf-8", errors="replace"
                            )
                            new_cls, cls_act = FontHandler.repair_missing_font(
                                cls_content, missing_font
                            )
                            if cls_act:
                                cls_file.write_text(new_cls, encoding="utf-8")
                                log.info(
                                    "repair_engine: repaired font %s in %s",
                                    missing_font,
                                    cls_file.name,
                                )
                                return source, cls_act
                        except (OSError, ValueError) as e:
                            log.warning(
                                "failed check font in %s: %s",
                                cls_file.name,
                                e,
                            )

                new_src, action = FontHandler.repair_missing_font(
                    source, missing_font
                )
                if action:
                    return new_src, action

        # 2. Color Error
        if category == "color":
            missing_color = ColorHandler.extract_missing_color(log_text)
            if missing_color:
                new_src, action = ColorHandler.define_missing_color(
                    source, missing_color
                )
                if action:
                    return new_src, action

        # 3. Figure Error
        if category == "figure":
            missing_fig = FigureHandler.extract_missing_figure(log_text)
            if missing_fig:
                new_src, action = FigureHandler.substitute_figure(
                    source, missing_fig, compile_dir=compile_dir
                )
                if action:
                    return new_src, action

        # 4. Math Error
        if category == "math":
            new_src, action = MathHandler.inject_math_packages(source)
            if action:
                return new_src, action

        # 5. Table Error
        if category == "table":
            new_src, action = TableHandler.inject_table_packages(source)
            if action:
                return new_src, action

        # 6. Package or File Error
        if category == "package_or_file":
            missing_file = PackageHandler.extract_missing_file(log_text)
            if missing_file:
                new_src, action = PackageHandler.repair_missing_file(
                    source, missing_file, compile_dir=compile_dir
                )
                if action:
                    return new_src, action

        # 7. Citation Error
        if category == "citation":
            missing_cite = CitationHandler.extract_missing_citation(log_text)
            if missing_cite:
                new_src, action = CitationHandler.insert_placeholder_bibitem(
                    source, missing_cite
                )
                if action:
                    return new_src, action

        # Fallback chain: if primary category didn't apply,
        # test remaining handlers
        if MathHandler.is_math_error(log_text):
            new_src, action = MathHandler.inject_math_packages(source)
            if action:
                return new_src, action

        if TableHandler.is_table_error(log_text):
            new_src, action = TableHandler.inject_table_packages(source)
            if action:
                return new_src, action

        missing_c = ColorHandler.extract_missing_color(log_text)
        if missing_c:
            new_src, action = ColorHandler.define_missing_color(
                source, missing_c
            )
            if action:
                return new_src, action

        missing_f = FigureHandler.extract_missing_figure(log_text)
        if missing_f:
            new_src, action = FigureHandler.substitute_figure(
                source, missing_f, compile_dir=compile_dir
            )
            if action:
                return new_src, action

        missing_pkg = PackageHandler.extract_missing_file(log_text)
        if missing_pkg:
            new_src, action = PackageHandler.repair_missing_file(
                source, missing_pkg, compile_dir=compile_dir
            )
            if action:
                return new_src, action

        missing_ct = CitationHandler.extract_missing_citation(log_text)
        if missing_ct:
            new_src, action = CitationHandler.insert_placeholder_bibitem(
                source, missing_ct
            )
            if action:
                return new_src, action

        return source, None
