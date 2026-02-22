import re
from typing import Dict, List


class SectionNode:
    def __init__(self, title: str, content: str, raw_match: str):
        self.title = title
        self.content = content
        self.raw_match = raw_match


class SectionalParser:
    """Parses and extracts sections from LaTeX code."""

    def __init__(self):
        # Pattern to find \section{Title} until next section or end
        self.SECTION_PATTERN = re.compile(
            r"(?P<raw>\\section\{(?P<title>(?:[^{}]|\{[^{}]*\})+)\}"
            r"(?P<content>.*?))"
            r"(?=\\section|\\end\{document\}|$)",
            re.DOTALL,
        )

    def _clean_title(self, title: str) -> str:
        """Removes LaTeX formatting from title for internal mapping."""
        return re.sub(r"\\[^{}]+\{|\}", "", title).strip()

    def get_preamble(self, latex: str) -> str:
        """Extracts everything before the first section."""
        first_match = self.SECTION_PATTERN.search(latex)
        if first_match:
            return latex[: first_match.start()].strip()
        return latex

    def extract_sections(self, latex: str) -> Dict[str, str]:
        """Extracts all sections and their content as a flat dictionary."""
        sections = {}
        for match in self.SECTION_PATTERN.finditer(latex):
            clean_title = self._clean_title(match.group("title"))
            sections[clean_title] = match.group("content").strip()
        return sections

    def get_structured_document(self, latex: str) -> List[Dict]:
        """Returns a list of nodes (preamble, sections, epilogue)."""
        nodes = []
        last_pos = 0

        # Preamble
        first_match = self.SECTION_PATTERN.search(latex)
        if first_match:
            nodes.append(
                {"type": "preamble", "content": latex[: first_match.start()]}
            )
            last_pos = first_match.start()
        else:
            nodes.append({"type": "preamble", "content": latex})
            return nodes

        for match in self.SECTION_PATTERN.finditer(latex):
            nodes.append(
                {
                    "type": "section",
                    "title": self._clean_title(match.group("title")),
                    "raw_title": match.group("title"),
                    "content": match.group("content"),
                    "raw": match.group("raw"),
                }
            )
            last_pos = match.end()

        # Anything after the last section (usually \end{document})
        nodes.append({"type": "epilogue", "content": latex[last_pos:]})

        return nodes

    def replace_section(
        self, full_latex: str, section_title: str, new_content: str
    ) -> str:
        """Replaces a specific section's content in the full LaTeX."""
        sections = self.get_structured_document(full_latex)
        updated_latex = ""
        found = False

        for node in sections:
            if node["type"] == "section" and node["title"] == section_title:
                updated_latex += (
                    f"\\section{{{node['raw_title']}}}\n{new_content}\n\n"
                )
                found = True
            elif node["type"] == "section":
                updated_latex += node["raw"]
            else:
                updated_latex += node["content"]

        if not found:
            # Fallback: Append before \end{document}
            if r"\end{document}" in updated_latex:
                new_sec = f"\\section{{{section_title}}}\n{new_content}\n"
                return updated_latex.replace(
                    "\\end{document}",
                    f"{new_sec}\n\\end{{document}}"
                )

        return updated_latex


# Singleton instance
sectional_parser = SectionalParser()
