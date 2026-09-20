"""Tool definitions, schemas, and descriptors for tree-based orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# High-level category for the first branch of the decision tree
RouteCategory = Literal["direct_reply", "structure", "content", "style"]


class CategoryDecision(BaseModel):
    """High-level classification returned by the Main Router."""

    route: RouteCategory = Field(
        ...,
        description=(
            "Routing category: 'direct_reply' for questions/chitchat, "
            "'structure' for adding/removing/reordering sections, "
            "'content' for modifying text inside a section or filling bio, "
            "'style' for changing fonts, colors, margins, or layout."
        ),
    )
    reason: str = Field(
        default="",
        description="Brief rationale for the routing decision.",
    )
    reply: str | None = Field(
        default=None,
        description=(
            "Direct conversational response when route is 'direct_reply'."
        ),
    )


# --- Structure Branch Tools ---


class AddZoneTool(BaseModel):
    """Tool: Add a new section/zone to the resume layout."""

    tool_name: Literal["add_zone"] = "add_zone"
    title: str = Field(
        ...,
        description=(
            "Title or description of the new section (e.g. 'Projects', "
            "'Certifications')."
        ),
    )
    after_zone_no: int | None = Field(
        default=None,
        description=(
            "Existing zone number after which this new section should be "
            "inserted."
        ),
    )
    at_start: bool = Field(
        default=False,
        description=(
            "True if the new section should be inserted at the very top."
        ),
    )


class RemoveZoneTool(BaseModel):
    """Tool: Delete one or more complete sections/zones from the resume."""

    tool_name: Literal["remove_zone"] = "remove_zone"
    zone_nos: list[int] = Field(
        ...,
        description="List of zone numbers to permanently delete.",
    )


class ReorderZonesTool(BaseModel):
    """Tool: Rearrange or swap the sequence of sections in the resume."""

    tool_name: Literal["reorder_zones"] = "reorder_zones"
    new_order: list[int] | None = Field(
        default=None,
        description="Complete list of all zone numbers in desired order.",
    )
    swap: list[int] | None = Field(
        default=None,
        description="Pair of two zone numbers to swap positions (e.g. [2, 4]).",
    )


# --- Content Branch Tools ---


class EditZoneContentTool(BaseModel):
    """Tool: Edit or update text/bullets inside an existing resume section."""

    tool_name: Literal["edit_zone_content"] = "edit_zone_content"
    zone_no: int = Field(
        ...,
        description="Target zone number where content should be updated.",
    )
    instructions: str = Field(
        default="",
        description="Detailed editing instructions for what to change.",
    )


class FillResumeTool(BaseModel):
    """Tool: Fill multiple or all resume sections from biographical text."""

    tool_name: Literal["fill_resume"] = "fill_resume"
    zone_nos: list[int] | None = Field(
        default=None,
        description=(
            "Optional subset of zone numbers to fill (defaults to all active)."
        ),
    )


# --- Style Branch Tools ---


class UpdateDocumentStyleTool(BaseModel):
    """Tool: Update document style, fonts, colors, margins, or layout."""

    tool_name: Literal["update_document_style"] = "update_document_style"
    font_family: str | None = Field(
        default=None,
        description=(
            "Font family: 'times', 'helvetica', 'lmodern', "
            "'palatino', 'default'."
        ),
    )
    font_size: str | None = Field(
        default=None,
        description="Font size: '10pt', '11pt', '12pt'.",
    )
    color_theme: str | None = Field(
        default=None,
        description=(
            "Preset theme: 'blue', 'green', 'burgundy', 'slate', 'black'."
        ),
    )
    primary_color: str | None = Field(
        default=None,
        description="Hex primary color e.g. '#2563EB'.",
    )
    accent_color: str | None = Field(
        default=None,
        description="Hex accent color e.g. '#60A5FA'.",
    )
    text_color: str | None = Field(
        default=None,
        description="Hex body text color e.g. '#1F2937'.",
    )
    margins: str | None = Field(
        default=None,
        description="Margins: 'compact', 'normal', 'wide', '0.5in', '0.75in'.",
    )
    column_layout: str | None = Field(
        default=None,
        description="Layout: 'onecolumn' or 'twocolumn'.",
    )
    instructions: str = Field(
        default="",
        description="Specific instructions for document styling.",
    )


# --- Tool Descriptors for LLM Prompts ---

STRUCTURE_TOOLS_DESCRIPTION = """Available Structural Tools:
1. `add_zone`:
   Description: Inserts a brand new section into the resume.
   Arguments:
     - `title`: (string) Title of the new section.
     - `after_zone_no`: (optional integer) Place after this zone number.
     - `at_start`: (optional boolean) True if section belongs at beginning.

2. `remove_zone`:
   Description: Permanently deletes an entire section/zone from the resume.
   Arguments:
     - `zone_nos`: (list of integers) Zone numbers to remove.

3. `reorder_zones`:
   Description: Rearranges or swaps sequence of existing sections.
   Arguments:
     - `swap`: (list of two integers) e.g. [2, 3] to swap zone 2 and 3.
     - `new_order`: (list of integers) full list of zone numbers in order.

Return JSON format:
{"tool": "add_zone" | "remove_zone" | "reorder_zones", "args": {...}, "reason": "..."}"""

CONTENT_TOOLS_DESCRIPTION = """Available Content Tools:
1. `edit_zone_content`:
   Description: Edits text/bullets inside an existing section.
   Arguments:
     - `zone_no`: (integer) The single zone number to modify.
     - `instructions`: (string) Concise instructions for zone specialist.

2. `fill_resume`:
   Description: Populates empty zones or rewrites zones from bio data.
   Arguments:
     - `zone_nos`: (optional list of integers) Target zones or empty for all.

Return JSON format:
{"tool": "edit_zone_content" | "fill_resume", "args": {...}, "reason": "..."}"""

STYLE_TOOLS_DESCRIPTION = """Available Style Tools:
1. `update_document_style`:
   Description: Modifies document styling, fonts, colors, margins, or layout.
   Arguments:
     - `font_family`: (optional string) 'times', 'helvetica', 'lmodern', 'palatino', 'default'.
     - `font_size`: (optional string) '10pt', '11pt', '12pt'.
     - `color_theme`: (optional string) 'blue', 'green', 'burgundy', 'slate', 'black'.
     - `primary_color`: (optional string) hex color e.g. '#2563EB'.
     - `accent_color`: (optional string) hex color e.g. '#60A5FA'.
     - `text_color`: (optional string) hex color e.g. '#1F2937'.
     - `margins`: (optional string) 'compact', 'normal', 'wide', '0.5in', '0.75in'.
     - `column_layout`: (optional string) 'onecolumn' or 'twocolumn'.
     - `instructions`: (optional string) additional instructions.

Return JSON format:
{"tool": "update_document_style", "args": {...}, "reason": "..."}"""
