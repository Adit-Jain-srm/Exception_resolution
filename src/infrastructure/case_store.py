"""In-memory case store for development. Production would use PostgreSQL.

Provides atomic case state transitions with optimistic locking
and idempotency key tracking for deduplication.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..models.domain import AuditEntry, ExceptionCase
from ..models.enums import CaseStatus
from .state_machine import CaseStateMachine, InvalidTransitionError


class OptimisticLockError(Exception):
    def __init__(self, case_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"Optimistic lock failed for case {case_id}: "
            f"expected version {expected}, found {actual}"
        )


class CaseStore:
    """Thread-safe in-memory case store with optimistic locking."""

    def __init__(self) -> None:
        self._cases: dict[str, ExceptionCase] = {}
        self._idempotency_keys: set[str] = set()
        self._state_machines: dict[str, CaseStateMachine] = {}
        self._lock = asyncio.Lock()

    async def exists_by_idempotency_key(self, key: str) -> bool:
        return key in self._idempotency_keys

    async def save(self, case: ExceptionCase) -> ExceptionCase:
        async with self._lock:
            if case.idempotency_key:
                if case.idempotency_key in self._idempotency_keys:
                    existing = next(
                        (c for c in self._cases.values() if c.idempotency_key == case.idempotency_key),
                        None,
                    )
                    if existing:
                        return existing
                self._idempotency_keys.add(case.idempotency_key)

            self._cases[case.case_id] = case
            self._state_machines[case.case_id] = CaseStateMachine(case.status)
            return case

    async def get(self, case_id: str) -> ExceptionCase | None:
        return self._cases.get(case_id)

    async def transition(
        self,
        case_id: str,
        target_status: CaseStatus,
        agent: str,
        details: dict[str, Any] | None = None,
    ) -> ExceptionCase:
        """Atomically transition case status with optimistic locking."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError(f"Case {case_id} not found")

            sm = self._state_machines[case_id]
            sm.transition_to(target_status)

            case.status = target_status
            case.version += 1
            case.add_audit(agent=agent, action=f"transition_to_{target_status}", details=details or {})
            return case

    async def list_by_status(self, status: CaseStatus) -> list[ExceptionCase]:
        return [c for c in self._cases.values() if c.status == status]

    async def count(self) -> int:
        return len(self._cases)
