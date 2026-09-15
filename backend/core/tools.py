"""Tool definitions, schemas, and descriptors for the tree-based orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# High-level category for the first branch of the decision tree
RouteCategory = Literal["direct_reply", "structure", "content"]


class CategoryDecision(BaseModel):
    """High-level classification returned by the Main Router."""

    route: RouteCategory = Field(
        ...,
        description=(
            "Routing category: 'direct_reply' for questions/chitchat, "
            "'structure' for adding/removing/reordering sections, "
            "'content' for modifying text inside a section or filling bio."
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
            "Existing zone number after which this new section should be inserted."
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
        description="List of zone numbers to permanently delete from the resume.",
    )


class ReorderZonesTool(BaseModel):
    """Tool: Rearrange or swap the sequence of sections in the resume."""

    tool_name: Literal["reorder_zones"] = "reorder_zones"
    new_order: list[int] | None = Field(
        default=None,
        description="Complete list of all zone numbers in desired sequential order.",
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
            "Optional subset of zone numbers to fill (defaults to all active zones)."
        ),
    )


# --- Tool Descriptors for LLM Prompts ---

STRUCTURE_TOOLS_DESCRIPTION = """Available Structural Tools:
1. `add_zone`:
   Description: Inserts a brand new section into the resume.
   Arguments:
     - `title`: (string) Title of the new section (e.g. 'Certifications', 'Volunteering').
     - `after_zone_no`: (optional integer) Zone number after which to place the new section.
     - `at_start`: (optional boolean) True if the section belongs at the beginning.

2. `remove_zone`:
   Description: Permanently deletes an entire section/zone from the resume. ONLY use when deleting a full section (e.g. 'remove projects'). NEVER use when removing a single bullet point or item inside a section.
   Arguments:
     - `zone_nos`: (list of integers) Zone numbers to remove.

3. `reorder_zones`:
   Description: Rearranges or swaps the sequence of existing resume sections.
   Arguments:
     - `swap`: (list of two integers) e.g. [2, 3] to swap zone 2 and 3.
     - `new_order`: (list of integers) full list of zone numbers in desired order.

Return JSON format:
{"tool": "add_zone" | "remove_zone" | "reorder_zones", "args": {...}, "reason": "..."}"""

CONTENT_TOOLS_DESCRIPTION = """Available Content Tools:
1. `edit_zone_content`:
   Description: Edits, adds, rewrites, or deletes text/bullets INSIDE an existing section (e.g. 'change GPA', 'add python to skills', 'remove Google internship', 'make summary shorter').
   Arguments:
     - `zone_no`: (integer) The single zone number to modify.
     - `instructions`: (string) Concise instructions for the zone specialist.

2. `fill_resume`:
   Description: Populates empty zones or rewrites all zones from biographical profile data or full resume text.
   Arguments:
     - `zone_nos`: (optional list of integers) Target zones or empty for all.

Return JSON format:
{"tool": "edit_zone_content" | "fill_resume", "args": {...}, "reason": "..."}"""
