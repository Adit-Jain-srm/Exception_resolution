"""Ingress Gateway Agent — validates, normalizes, deduplicates exception events.

Persona: "The Ingress Guardian"
- Meticulous, skeptical, protective
- Rejects aggressively — false rejection is safer than bad data flowing through
- Never makes assumptions about missing fields
"""

from __future__ import annotations

import hashlib
import structlog
from datetime import datetime, timedelta, timezone

from ..models.domain import ExceptionCase, BeneficiaryDetails
from ..models.enums import (
    CaseStatus,
    ExceptionType,
    PaymentRail,
    PaymentType,
    Priority,
)
from ..infrastructure.case_store import CaseStore

logger = structlog.get_logger()


class ValidationError(Exception):
    """Raised when an incoming event fails schema validation."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"Validation failed on '{field}': {reason}")


class IngressGateway:
    """
    Receives raw exception events, validates, normalizes, deduplicates,
    and emits canonical ExceptionCase objects.
    """

    REQUIRED_FIELDS = {"payment_id", "client_id", "account_id", "payment_rail", "exception_type", "amount"}
    SLA_WINDOWS: dict[Priority, timedelta] = {
        Priority.CRITICAL: timedelta(minutes=5),
        Priority.HIGH: timedelta(minutes=15),
        Priority.MEDIUM: timedelta(hours=1),
        Priority.LOW: timedelta(hours=4),
    }

    def __init__(self, case_store: CaseStore) -> None:
        self._store = case_store
        self._rejected_count = 0
        self._accepted_count = 0
        self._duplicate_count = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "accepted": self._accepted_count,
            "rejected": self._rejected_count,
            "duplicates": self._duplicate_count,
        }

    async def process_event(self, event: dict) -> ExceptionCase | None:
        """
        Process a raw exception event. Returns ExceptionCase if accepted,
        None if deduplicated, raises ValidationError if rejected.
        """
        log = logger.bind(payment_id=event.get("payment_id", "UNKNOWN"))

        self._validate(event)

        idempotency_key = self._compute_idempotency_key(event)

        if await self._store.exists_by_idempotency_key(idempotency_key):
            self._duplicate_count += 1
            log.info("duplicate_event_rejected", idempotency_key=idempotency_key)
            return None

        case = self._normalize(event, idempotency_key)
        saved = await self._store.save(case)

        self._accepted_count += 1
        log.info(
            "case_created",
            case_id=saved.case_id,
            exception_type=saved.exception_type,
            priority=saved.priority,
        )
        return saved

    def _validate(self, event: dict) -> None:
        """Strict schema validation — reject if any required field missing or invalid."""
        for field in self.REQUIRED_FIELDS:
            if field not in event or event[field] is None:
                self._rejected_count += 1
                raise ValidationError(field, "required field missing")

        if not isinstance(event["amount"], (int, float, str)):
            self._rejected_count += 1
            raise ValidationError("amount", "must be numeric")

        try:
            amount = float(event["amount"])
        except (ValueError, TypeError):
            self._rejected_count += 1
            raise ValidationError("amount", "cannot parse as number")

        if amount <= 0:
            self._rejected_count += 1
            raise ValidationError("amount", "must be positive")

        try:
            PaymentRail(event["payment_rail"])
        except ValueError:
            self._rejected_count += 1
            raise ValidationError("payment_rail", f"invalid rail: {event['payment_rail']}")

        try:
            ExceptionType(event["exception_type"])
        except ValueError:
            self._rejected_count += 1
            raise ValidationError("exception_type", f"invalid type: {event['exception_type']}")

    def _compute_idempotency_key(self, event: dict) -> str:
        """Composite key: payment_id + exception_type + date (not timestamp for dedup window)."""
        raw = f"{event['payment_id']}:{event['exception_type']}:{datetime.now(timezone.utc).date()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _normalize(self, event: dict, idempotency_key: str) -> ExceptionCase:
        """Transform raw event into canonical ExceptionCase."""
        priority = self._compute_priority(event)
        now = datetime.now(timezone.utc)

        beneficiary = BeneficiaryDetails(
            name=event.get("beneficiary_name"),
            account_number=event.get("beneficiary_account"),
            ifsc_code=event.get("beneficiary_ifsc"),
            routing_number=event.get("beneficiary_routing"),
            bank_name=event.get("beneficiary_bank"),
            upi_id=event.get("beneficiary_upi"),
        )

        return ExceptionCase(
            payment_id=event["payment_id"],
            client_id=event["client_id"],
            account_id=event["account_id"],
            payment_rail=PaymentRail(event["payment_rail"]),
            payment_type=PaymentType(event.get("payment_type", "DOMESTIC")),
            exception_type=ExceptionType(event["exception_type"]),
            amount=event["amount"],
            currency=event.get("currency", "INR"),
            beneficiary_details=beneficiary,
            status=CaseStatus.RECEIVED,
            priority=priority,
            created_at=now,
            updated_at=now,
            sla_deadline=now + self.SLA_WINDOWS[priority],
            idempotency_key=idempotency_key,
        )

    def _compute_priority(self, event: dict) -> Priority:
        """Priority based on amount and exception type."""
        amount = float(event["amount"])
        exception_type = event["exception_type"]

        if exception_type == ExceptionType.COMPLIANCE_HOLD:
            return Priority.HIGH

        if amount >= 1_000_000:
            return Priority.CRITICAL
        elif amount >= 100_000:
            return Priority.HIGH
        elif amount >= 10_000:
            return Priority.MEDIUM
        return Priority.LOW
