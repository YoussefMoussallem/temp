"""`cost` — show the user's all-time usage and cost.

Reads the caller's ``authorization`` off the per-turn ``ToolUseContext`` and
asks the db-service for ``/api/usage/me`` (a typed dict of per-model totals
plus the user's email). Failure modes are turned into friendly messages —
this command is informational, never on the critical path.

Holds both the Command definition and its ``call`` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from app_logger import get_logger
from app.db import usage

from ...types.command import Command

log = get_logger(__name__)


async def call(_args: str, ctx: Any) -> dict:
    authorization = getattr(ctx, "authorization", None)
    if not authorization:
        return {
            "type": "value",
            "value": "Cost data unavailable: no auth on the request context.",
        }

    try:
        result = await usage.get_my_usage(authorization)
    except Exception as e:  # noqa: BLE001
        log.warning("get_my_usage failed: %s", e)
        result = None

    if not result:
        return {"type": "value", "value": "Couldn't fetch usage data right now."}

    totals = result.get("totals") or []
    email = result.get("email") or ""

    if not totals:
        msg = f"No usage recorded yet for {email}." if email else "No usage recorded yet."
        return {"type": "value", "value": msg}

    total_cost = sum(float(t.get("total_cost_usd") or 0) for t in totals)
    total_input = sum(int(t.get("total_input_tokens") or 0) for t in totals)
    total_output = sum(int(t.get("total_output_tokens") or 0) for t in totals)
    total_requests = sum(int(t.get("record_count") or 0) for t in totals)
    total_tokens = total_input + total_output

    lines = [
        f"Total: ${total_cost:.4f} — {total_tokens:,} tokens "
        f"({total_input:,} in / {total_output:,} out, {total_requests} requests)",
    ]
    if len(totals) > 1:
        lines.append("")
        lines.append("By model:")
        for t in sorted(totals, key=lambda x: float(x.get("total_cost_usd") or 0), reverse=True):
            model = t.get("model", "unknown")
            cost_v = float(t.get("total_cost_usd") or 0)
            inp = int(t.get("total_input_tokens") or 0)
            outp = int(t.get("total_output_tokens") or 0)
            reqs = int(t.get("record_count") or 0)
            lines.append(f"  {model}: ${cost_v:.4f}, {inp + outp:,} tokens, {reqs} requests")
    if email:
        lines.append("")
        lines.append(f"Account: {email}")

    return {"type": "value", "value": "\n".join(lines)}


async def _load():
    return import_module(__name__)


cost: Command = cast(
    Command,
    {
        "type": "local",
        "execution": "server",
        "name": "cost",
        "description": "Show your usage and cost",
        "aliases": [],
        "supports_non_interactive": True,
        "load": _load,
    },
)
