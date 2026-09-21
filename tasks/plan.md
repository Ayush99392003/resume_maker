# Implementation Plan: Dynamic Interactive Zones & Layout Reordering

## Overview
Currently, zones in the resume and research paper modes are rendered as static pills. Clicking anywhere on a pill prompts to delete it, drag-and-drop reordering is not implemented, adding a zone only appends to the document end without position control, and zone changes do not automatically recompile the PDF.
This plan implements production-grade dynamic interactive zones:
1. **Frontend Drag-and-Drop & Quick-Move Controls**: Interactive HTML5 drag-and-drop for zone chips with visual indicators, separate click-to-select from removal, and left/right single-slot shift buttons for accessibility.
2. **Position-Aware Add Zone Modal**: Intuitive modal to specify zone title and insert position ("At start", "After Z...", "At end") with mode-aware starter LaTeX.
3. **Automatic Compilation Pipeline**: Immediate auto-compilation (`compileAndRender`) following any reorder, add, or remove action to instantly refresh the PDF preview.
4. **Backend Robustness & Natural Language Zone Orchestration**: Safe partial reordering in `ZoneDocument.reorder()`, mode-aware default LaTeX in `POST /zones`, and multi-step structure support (`add_zone` + `reorder_zones`/`move`) in the AI Orchestrator.

---

## Architecture Decisions
- **Native HTML5 Drag-and-Drop with Visual Cues**: Implement drag-and-drop in `frontend/src/App.jsx` using standard HTML5 DnD APIs to avoid adding heavy external drag-and-drop dependencies. Include drag preview opacity, drop target rings, and clear drop targets.
- **Accidental Deletion Prevention**: Isolate the delete action exclusively to the `X` button with `e.stopPropagation()`. Clicking the pill body selects the zone as the active target zone (`selectedTargetZone`).
- **Dual Reordering UX (Drag + Buttons)**: Provide both drag-and-drop and one-click move arrows (`‹` and `›`) on each pill so users on trackpads, keyboards, and mobile can reorder with zero friction.
- **Mode-Aware Starter LaTeX**: Academic papers use numbered `\section{...}` by default, whereas resumes use unnumbered `\section*{...}` or bullet environments.
- **Auto-Compiling Zone State**: Every zone structural change (reorder, add, remove) immediately triggers `compileAndRender` so the user never has to manually hit compile to see layout changes in the PDF.

---

## Task List

### Phase 1: Backend Robustness & AI Orchestration
- [ ] Task 1: Enhance `ZoneDocument.reorder()` in `backend/core/zone_document.py` to gracefully handle partial/fuzzy order lists without raising `ValueError`.
- [ ] Task 2: Enhance `add_zone` in `backend/main.py` and `ZoneDocument` to provide mode-aware default LaTeX (`\section{...}` for academic papers, `\section*{...}` for resumes).
- [ ] Task 3: Support `move` arguments and multi-action steps in `backend/core/tools.py` and `backend/core/orchestrator.py` so requests like "bring Methodology to Z6 and add RELATED WORK at Z5" can be executed in a single turn.

### Checkpoint: Backend Zone Tests
- [ ] Unit tests pass for `ZoneDocument.reorder`, `ZoneDocument.move`, and `orchestrator` structure planning.

### Phase 2: Frontend Interactive Zone Bar & Drag-and-Drop
- [ ] Task 4: In `frontend/src/App.jsx`, implement `reorderZones(newOrder)` calling `PATCH /sessions/{sessionId}/zone-order`, updating state, and invoking `compileAndRender`.
- [ ] Task 5: Implement HTML5 Drag-and-Drop (`draggable`, `onDragStart`, `onDragOver`, `onDrop`, `onDragEnd`) with visual indicators on zone chips.
- [ ] Task 6: Separate click handlers (pill clicks select `selectedTargetZone`, `X` button exclusively removes zone) and add quick-move arrows (`‹` / `›`) to each chip.

### Phase 3: Position-Aware Add Zone Modal & Instant Compilation
- [ ] Task 7: Build `AddZoneModal` in `frontend/src/App.jsx` allowing users to choose zone title, target position ("At start", "After Z...", "At end"), and submit to `POST /sessions/{sessionId}/zones`.
- [ ] Task 8: Trigger immediate auto-compilation (`compileAndRender`) after add, remove, and reorder operations with status feedback ("Layout updated · Compiling preview...").

### Checkpoint: End-to-End Verification
- [ ] Moving zone pills in UI updates layout and re-renders PDF.
- [ ] Adding a zone at a specific position (e.g. "RELATED WORK at Z5") compiles correctly and places the new section at the specified slot.
- [ ] Natural language chat request ("move Methodology to Z6 and add RELATED WORK at Z5") executes and compiles cleanly.

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Rapid repeated dragging causing concurrent compile requests | Med | Debounce or use `compile_semaphore` and quiet auto-syncing during rapid moves. |
| Incomplete zone lists in AI-generated reorder commands | Med | `ZoneDocument.reorder` reconciles specified zones first and appends remaining existing zones. |
| Drag-and-drop quirks on touch screens / trackpads | Low | Provide discrete `‹` and `›` buttons on chips alongside drag-and-drop. |
