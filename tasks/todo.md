# Tasks: Dynamic Interactive Zones & Layout Reordering

## Task 1: Resilient `ZoneDocument.reorder()` and `doc.move()`
**Description:** Update `ZoneDocument.reorder()` in `backend/core/zone_document.py` to be fault-tolerant: if a caller or LLM passes a partial list or extra IDs, retain the specified order for known IDs and append the remaining document zones in their existing order. Also ensure `doc.move(zone_no, target_index=...)` supports 1-based or 0-based target slot indexing.

**Acceptance criteria:**
- [x] `doc.reorder([3, 1])` on zones `[1, 2, 3, 4]` produces `[3, 1, 2, 4]` without throwing `ValueError`.
- [x] Existing full-order reorder calls continue to work identically.
- [x] `doc.move(zone_no, target_index=...)` allows moving directly to a slot index.

**Verification:**
- [x] Tests pass: `uv run pytest tests/test_latex_to_zones.py tests/test_zones.py -v`

**Files likely touched:**
- `backend/core/zone_document.py`
- `tests/test_latex_to_zones.py`

---

## Task 2: Mode-Aware Zone Addition LaTeX
**Description:** In `backend/main.py` and `ZoneDocument.add_zone()`, generate mode-aware starter LaTeX. In `research_paper` mode, default to `\section{Title}\n% Content for Title\n` (numbered academic section). In `resume` mode, default to `\section*{Title}\n\begin{itemize}\n  \item ...\n\end{itemize}\n`.

**Acceptance criteria:**
- [x] Adding a zone in `research_paper` mode produces standard `\section{...}`.
- [x] Adding a zone in `resume` mode produces `\section*{...}`.

**Verification:**
- [x] Run test verifying zone addition in both modes (`test_mode_aware_add_zone`).

**Files likely touched:**
- `backend/main.py`
- `backend/core/zone_document.py`

---

## Task 3: Multi-Action and Move Support in AI Orchestrator
**Description:** In `backend/core/tools.py` and `backend/core/orchestrator.py`, update `STRUCTURE_TOOLS_DESCRIPTION` and `plan_intents` to support `move` arguments (`zone_no`, `to_position`, `after_zone_no`) and composite structural actions so instructions like "bring Methodology to Z6 and add RELATED WORK at Z5" produce both steps.

**Acceptance criteria:**
- [x] Natural language request to move a zone to a position generates an appropriate `reorder`/`move` step.
- [x] Multi-action prompts produce multiple sequential `OrchStep`s executed in order.

**Verification:**
- [x] Tests pass: `uv run pytest tests/test_tree_router_benchmark.py -v`

**Files likely touched:**
- `backend/core/tools.py`
- `backend/core/orchestrator.py`

---

## Checkpoint: Backend Zone Capabilities Verified
- [x] All pytest tests pass for zone document and orchestrator (91 tests passing).

---

## Task 4: Frontend `reorderZones()` and Auto-Compilation
**Description:** In `frontend/src/App.jsx`, implement `reorderZones(newOrder)` that sends `PATCH /sessions/${sessionId}/zone-order`, updates `zoneCatalog` and `latexCode`, and calls `compileAndRender(resp.data.latex_code, sessionId, { quiet: false })`.

**Acceptance criteria:**
- [x] `reorderZones` sends the new numeric array to the backend.
- [x] State is synchronized and `compileAndRender` triggers immediately.

**Files likely touched:**
- `frontend/src/App.jsx`

---

## Task 5: Frontend HTML5 Drag-and-Drop with Visual Indicators
**Description:** In `frontend/src/App.jsx`, implement HTML5 drag-and-drop on zone chips (`draggable={true}`, `onDragStart`, `onDragOver`, `onDragLeave`, `onDrop`, `onDragEnd`). Provide visual cues: dragging chip opacity 40%, drag-over target ring/border highlight.

**Acceptance criteria:**
- [x] User can grab any zone chip and drop it onto another zone chip.
- [x] Dropping reorders the zones and triggers `reorderZones()`.
- [x] Visual indicators show where the item will land.

**Files likely touched:**
- `frontend/src/App.jsx`

---

## Task 6: Pill Interaction Separation & Quick-Move Buttons
**Description:** In `frontend/src/App.jsx`:
1. Make clicking the chip body select `selectedTargetZone` (highlighting active zone in chat).
2. Isolate `removeZone` to the `X` button with `e.stopPropagation()`.
3. Add quick-move left (`‹`) and right (`›`) buttons to each chip for 1-click single-slot moves.

**Acceptance criteria:**
- [x] Clicking a chip body does NOT prompt to delete; it selects the zone for chat.
- [x] Clicking `X` confirms and deletes the zone.
- [x] Clicking `‹` moves the zone left one position; clicking `›` moves it right.

**Files likely touched:**
- `frontend/src/App.jsx`

---

## Task 7: Position-Aware `AddZoneModal`
**Description:** Create a modal/dialog in `frontend/src/App.jsx` for adding a zone. Includes fields for Zone Title (e.g. "RELATED WORK") and Placement ("At start", "After [Zone ...]", "At end"). Submits to `POST /sessions/${sessionId}/zones` with `after_zone_no` or `at_start`, and triggers `compileAndRender`.

**Acceptance criteria:**
- [x] Clicking "+ Add zone" opens the modal instead of a simple `window.prompt`.
- [x] User can select insertion position.
- [x] New zone appears at the requested position in `zoneCatalog` and PDF updates immediately.

**Files likely touched:**
- `frontend/src/App.jsx`

---

## Checkpoint: End-to-End Verification Complete
- [x] Frontend builds cleanly: `npm run build` completed with 0 errors.
- [x] All backend unit tests continue to pass with 0 regressions (91 tests passed).
