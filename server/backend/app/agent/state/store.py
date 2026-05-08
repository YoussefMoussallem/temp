"""
Observable store pattern.

Port of src/state/store.ts. Useful for in-flight state tracking with
subscribe/setState semantics. Backend doesn't persist between requests
(stateless), but the pattern is handy for per-request state with multiple
observers (e.g., progress event emitters watching cost accumulation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")

Listener = Callable[[], None]
Updater = Callable[[T], T]
OnChange = Callable[["OnChangeArgs[T]"], None]


@dataclass
class OnChangeArgs(Generic[T]):
    newState: T
    oldState: T


class Store(Generic[T]):
    """Observable store with functional updates."""

    def __init__(
        self,
        initial_state: T,
        on_change: OnChange | None = None,
    ) -> None:
        self._state = initial_state
        self._listeners: set[Listener] = set()
        self._on_change = on_change

    def get_state(self) -> T:
        return self._state

    def set_state(self, updater: Updater) -> None:
        prev = self._state
        next_state = updater(prev)
        # `is` check matches TS Object.is — bail out if unchanged.
        if next_state is prev:
            return
        self._state = next_state
        if self._on_change:
            self._on_change(OnChangeArgs(newState=next_state, oldState=prev))
        for listener in list(self._listeners):
            listener()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe


def create_store(
    initial_state: T,
    on_change: OnChange | None = None,
) -> Store[T]:
    return Store(initial_state, on_change)
