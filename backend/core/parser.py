import re
from typing import Dict


class SectionalParser:
    """Parses and extracts sections from LaTeX code."""

    # More robust pattern to find \section{Title}
    # It looks for \section, then matches anything inside { } (handling one
    # level of nesting if needed) and captures content until the next
    # section or end of document.
    SECTION_PATTERN = re.compile(
        r'\\section\{(?P<title>(?:[^{}]|\{[^{}]*\})+)\}'
        r'(?P<content>.*?)'
        r'(?=\\section|\\end\{document\}|$)',
        re.DOTALL
    )

    def extract_sections(self, latex: str) -> Dict[str, str]:
        """
        Extracts all sections and their content.
        """
        sections = {}
        for match in self.SECTION_PATTERN.finditer(latex):
            title = match.group('title').strip()
            # Remove any LaTeX formatting from title for internal mapping
            clean_title = re.sub(r'\\[^{}]+\{|\}', '', title).strip()
            content = match.group('content').strip()
            sections[clean_title] = content
        return sections

    def replace_section(self,
                        full_latex: str,
                        section_title: str,
                        new_content: str) -> str:
        """
        Replaces a specific section's content in the full LaTeX document.
        """
        # Finds the section with the same title (ignoring minor formatting)
        # and replaces its content.
        pattern = re.compile(
            rf'(\\section\{{.*?{re.escape(section_title)}.*?\}}).*?'
            rf'(?=\\section|\\end{{document}}|$)',
            re.DOTALL
        )

        replacement = f"\\1\n{new_content}\n\n"
        updated_latex, count = pattern.subn(replacement, full_latex)

        if count == 0:
            # If section not found, append before \end{document}
            end_marker = "\\end{document}"
            if end_marker in full_latex:
                new_sec = f"\\section{{{section_title}}}\n{new_content}\n"
                return full_latex.replace(
                    end_marker,
                    f"{new_sec}\n{end_marker}"
                )

        return updated_latex


# Singleton instance
sectional_parser = SectionalParser()
