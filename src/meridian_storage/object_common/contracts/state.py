# SPDX-License-Identifier: Apache-2.0
"""The normative Object put state machine."""

from __future__ import annotations

from enum import StrEnum
from threading import RLock

from ..errors import ObjectInvalidRequest


class PutState(StrEnum):
    NEW = "NEW"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    ORPHAN_CANDIDATE = "ORPHAN_CANDIDATE"


_TRANSITIONS: dict[PutState, frozenset[PutState]] = {
    PutState.NEW: frozenset({PutState.UPLOADING, PutState.ABORTED}),
    PutState.UPLOADING: frozenset(
        {PutState.VERIFYING, PutState.ABORTED, PutState.ORPHAN_CANDIDATE}
    ),
    PutState.VERIFYING: frozenset(
        {PutState.COMMITTED, PutState.ABORTED, PutState.ORPHAN_CANDIDATE}
    ),
    PutState.COMMITTED: frozenset(),
    PutState.ABORTED: frozenset(),
    PutState.ORPHAN_CANDIDATE: frozenset(),
}


class PutStateMachine:
    """Thread-safe transition helper; terminal states cannot be reopened."""

    def __init__(self) -> None:
        self._state = PutState.NEW
        self._history = [PutState.NEW]
        self._lock = RLock()

    @property
    def state(self) -> PutState:
        with self._lock:
            return self._state

    @property
    def history(self) -> tuple[PutState, ...]:
        with self._lock:
            return tuple(self._history)

    def transition(self, state: PutState | str) -> PutState:
        requested = PutState(state)
        with self._lock:
            if requested not in _TRANSITIONS[self._state]:
                raise ObjectInvalidRequest(
                    f"invalid Object put transition {self._state.value}->{requested.value}",
                    operation_contract="meridian.object.put",
                )
            self._state = requested
            self._history.append(requested)
            return requested

    def fail(self, *, physical_commit_possible: bool) -> PutState:
        target = PutState.ORPHAN_CANDIDATE if physical_commit_possible else PutState.ABORTED
        return self.transition(target)


__all__ = ["PutState", "PutStateMachine"]
