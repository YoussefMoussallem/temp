"""
Command lifecycle notifier.

Port of src/utils/commandLifecycle.ts. A single process-wide listener slot —
the /turn handler installs one at request start, clears it in `finally`.

Source semantics: "started" fires when the loop consumes a command_uuid
(i.e. the prompt-type command's tagged messages hit the model). "completed"
fires only on normal turn end; if the turn throws/cancels, `completed` is
never emitted — that asymmetry is the "failure" signal callers listen for.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable, Literal, Optional

CommandLifecycleState = Literal["started", "completed"]
CommandLifecycleListener = Callable[[str, CommandLifecycleState], None]


# ContextVar so concurrent /turn tasks each get their own listener. Source
# (single-user TUI) uses a module global; web backend needs per-request.
_listener_var: ContextVar[Optional[CommandLifecycleListener]] = ContextVar(
    "command_lifecycle_listener", default=None
)


def set_command_lifecycle_listener(listener: Optional[CommandLifecycleListener]):
    """Install (or clear with None) the listener for the current task.

    Returns the ContextVar token — pass it to ``reset_command_lifecycle_listener``
    in a ``finally`` to restore the prior value.
    """
    return _listener_var.set(listener)


def reset_command_lifecycle_listener(token) -> None:
    """Restore the prior listener. Safe to call with a token from set()."""
    try:
        _listener_var.reset(token)
    except Exception:  # noqa: BLE001
        pass


def notify_command_lifecycle(uuid: str, state: CommandLifecycleState) -> None:
    """Fire a lifecycle event. No-op if no listener is registered."""
    listener = _listener_var.get()
    if listener is None:
        return
    try:
        listener(uuid, state)
    except Exception:  # noqa: BLE001
        # Never let a listener exception corrupt the loop. Fire-and-forget.
        pass
