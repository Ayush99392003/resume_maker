"""One-shot script to surgically repair all corrupted session JSON files."""
import sys
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

SESSION_DIR = Path("backend/data/sessions")

MACRO_NAMES = [
    "resumeSubHeadingListStart", "resumeSubHeadingListEnd",
    "resumeSubheading", "resumeSubSubheading",
    "resumeProjectHeading",
    "resumeItemListStart", "resumeItemListEnd",
    "resumeItem", "resumeSubItem",
]


def repair(latex: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    orig = latex

    # 1. Normalize multiple backslashes before known macros to exactly ONE
    for macro in MACRO_NAMES:
        new, n = re.subn(r"\\{2,}" + re.escape(macro), r"\\" + macro, latex)
        if n:
            changes.append(f"+{n} fix \\\\+{macro}")
            latex = new

    # 2. Fix bare `section{` at line start (missing backslash)
    new, n = re.subn(r"(?m)^(\s*)section\{", r"\1\\section{", latex)
    if n:
        changes.append(f"+{n} fix bare section{{")
        latex = new

    # 3. Fix dollar sign: stored as `$\$` (open-math + escaped-dollar)
    #    The bad byte sequence in the stored string (Python value):
    #    dollar + backslash + dollar  → should be backslash + dollar only
    #    Tectonic sees: $  (opens math mode) then \$ (escaped dollar in math)
    #    then unclosed math. Fix: remove the spurious bare $ before \$
    new, n = re.subn(r"\$\\\$", r"\\$", latex)
    if n:
        changes.append(f"+{n} fix $\\$ dollar")
        latex = new

    # 4. Fix embedded literal \\n sequences (LLM returned newline as \\n string)
    #    Only fix when preceded by a TeX macro character pattern
    if r"\n" in latex and "\n" in latex:
        # Check for \n that's literally backslash-n (not a real newline)
        # A real newline is chr(10). \n as text is chr(92)+chr(110)
        pass  # handled by json.loads normally; skip for now

    return latex, changes


def main() -> None:
    total_fixed = 0
    for f in sorted(SESSION_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_bytes().decode("utf-8", errors="replace"))
        except Exception as exc:
            print(f"skip {f.name}: {exc}")
            continue

        latex = data.get("latex_code", "")
        if not latex:
            continue

        fixed, changes = repair(latex)
        if fixed != latex:
            data["latex_code"] = fixed
            f.write_bytes(
                json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            )
            print(f"fixed {f.name}:")
            for c in changes:
                print(f"  {c}")
            total_fixed += 1
        else:
            print(f"clean {f.name}")

    print(f"\nDone. {total_fixed} session(s) repaired.")


if __name__ == "__main__":
    main()
