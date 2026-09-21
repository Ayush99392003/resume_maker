"""SSE streaming wrapper for orchestrated chat turns.

Wraps Orchestrator.run() so that each completed zone emits a ``progress``
Server-Sent Event.  The final ``result`` event carries the full JSON payload
identical to what POST /chat returns.

Architecture
-----------
- A ``queue.Queue`` is shared between the worker thread and the async
  generator.
- The worker thread runs ``orchestrator.run()`` in a ``ThreadPoolExecutor``
  and monkey-patches each zone's completion callback to push ``progress``
  events into the queue.
- The async generator yields SSE lines until it receives a sentinel
  ``{"_done": True}`` dict.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncGenerator
from typing import Any

from core.logging_setup import get_logger

log = get_logger("chat_stream")

_SENTINEL = {"_done": True}


def _sse_line(event_type: str, data: Any) -> str:
    """Format a single SSE message."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


async def stream_chat_turn(
    *,
    orchestrator,           # Orchestrator instance (imported in main)
    zone_agent_router,      # ZoneAgentRouter instance (for monkey-patch)
    document,               # ZoneDocument
    user_message: str,
    is_first_fill: bool,
    target_zone: str | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    # post-orchestration callback (compile + session save) —
    # called with OrchResult and returns the final response dict
    finalize_fn,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE text chunks.

    Yields:
        ``progress`` events as each zone completes.
        ``result``   event with the full final JSON payload.
        ``error``    event on any exception.
    """
    evt_queue: queue.Queue = queue.Queue()
    loop = asyncio.get_event_loop()

    # --- Monkey-patch ZoneAgentRouter to emit progress events --------
    # We wrap run_zone() so every completion fires a queue put.
    # This avoids touching the Orchestrator internals.

    original_run_zone = zone_agent_router.run_zone
    zone_count = len(document.zone_order)
    completed_count = 0
    _lock = threading.Lock()

    def _patched_run_zone(**kwargs):
        nonlocal completed_count
        result = original_run_zone(**kwargs)
        with _lock:
            completed_count += 1
            done = completed_count
        zone_no = kwargs.get("zone_no")
        zone_desc = kwargs.get("zone_description", f"Zone {zone_no}")
        evt_queue.put({
            "_type": "progress",
            "zone_no": zone_no,
            "description": zone_desc,
            "done_count": done,
            "total_count": zone_count,
        })
        return result

    zone_agent_router.run_zone = _patched_run_zone

    def _worker():
        """Runs in a thread; pushes events + sentinel to queue."""
        try:
            orch_result = orchestrator.run(
                user_message=user_message,
                document=document,
                is_first_fill=is_first_fill,
                target_zone=target_zone,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            # finalize_fn is a coroutine — schedule it on the event loop
            future = asyncio.run_coroutine_threadsafe(
                finalize_fn(orch_result), loop
            )
            final_payload = future.result(timeout=300)
            evt_queue.put({"_type": "result", "payload": final_payload})
        except Exception as exc:
            log.exception("chat_stream: worker error - %s", exc)
            evt_queue.put({"_type": "error", "detail": str(exc)})
        finally:
            evt_queue.put(_SENTINEL)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    try:
        while True:
            # Poll queue without blocking the event loop
            try:
                item = evt_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if item is _SENTINEL or item.get("_done"):
                break

            evt_type = item.get("_type", "progress")
            if evt_type == "progress":
                yield _sse_line("progress", {
                    "zone_no": item["zone_no"],
                    "description": item["description"],
                    "done_count": item["done_count"],
                    "total_count": item["total_count"],
                })
            elif evt_type == "result":
                yield _sse_line("result", item["payload"])
                break
            elif evt_type == "error":
                yield _sse_line("error", {"detail": item["detail"]})
                break
    finally:
        # Always restore original run_zone to avoid leaking the patch
        zone_agent_router.run_zone = original_run_zone
        thread.join(timeout=5)
