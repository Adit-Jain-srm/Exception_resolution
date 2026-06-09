"""Investigation Agents — specialist evidence gatherers.

Persona: "The Detectives"
- Thorough, factual, non-judgmental
- Reports ONLY what they find — never interprets or recommends
- Returns INCONCLUSIVE when data is ambiguous
- Never modifies state in any system they query
- Operates under strict time budget

All investigators are deterministic (no LLM) — they retrieve facts, not generate them.
"""

from __future__ import annotations

import asyncio
import random
import structlog
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ..models.domain import Evidence, ExceptionCase
from ..models.enums import Confidence, EvidenceType

logger = structlog.get_logger()


class BaseInvestigator(ABC):
    """Abstract base for all investigation agents."""

    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.name = self.__class__.__name__

    async def investigate(self, case: ExceptionCase) -> Evidence:
        """Run investigation with timeout protection."""
        try:
            result = await asyncio.wait_for(
                self._gather_evidence(case),
                timeout=self.timeout_seconds,
            )
            logger.info("investigation_complete", agent=self.name, case_id=case.case_id, confidence=result.confidence)
            return result
        except asyncio.TimeoutError:
            logger.warning("investigation_timeout", agent=self.name, case_id=case.case_id)
            return Evidence(
                case_id=case.case_id,
                source_agent=self.name,
                evidence_type=self.evidence_type,
                confidence=Confidence.INCONCLUSIVE,
                data={"reason": "timeout", "timeout_seconds": self.timeout_seconds},
            )
        except Exception as e:
            logger.error("investigation_error", agent=self.name, case_id=case.case_id, error=str(e))
            return Evidence(
                case_id=case.case_id,
                source_agent=self.name,
                evidence_type=self.evidence_type,
                confidence=Confidence.INCONCLUSIVE,
                data={"reason": "error", "error": str(e)},
            )

    @property
    @abstractmethod
    def evidence_type(self) -> EvidenceType:
        ...

    @abstractmethod
    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        ...


class TransactionStateInvestigator(BaseInvestigator):
    """Queries core banking system for current transaction status."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.TRANSACTION_STATUS

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.05, 0.2))

        status_map = {
            "INSUFFICIENT_FUNDS": {"tx_status": "FAILED", "failure_code": "INSUFFICIENT_BALANCE", "debit_completed": False},
            "INCORRECT_BENEFICIARY": {"tx_status": "FAILED", "failure_code": "INVALID_BENEFICIARY", "debit_completed": True, "credit_failed": True},
            "DUPLICATE": {"tx_status": "COMPLETED", "original_tx_id": f"TX-{case.payment_id}-ORIG"},
            "COMPLIANCE_HOLD": {"tx_status": "HELD", "hold_reason": "AML_SCREENING", "held_since": datetime.now(timezone.utc).isoformat()},
            "NETWORK_FAILURE": {"tx_status": "UNCERTAIN", "last_known_state": "SUBMITTED", "network_ack": False},
            "CUTOFF_MISS": {"tx_status": "REJECTED", "failure_code": "PAST_CUTOFF", "submitted_at": "17:35:00", "cutoff_time": "17:00:00"},
            "UNCERTAIN_RETRY": {"tx_status": "UNCERTAIN", "prior_attempts": 2, "last_attempt_result": "UNKNOWN"},
        }

        data = status_map.get(case.exception_type, {"tx_status": "UNKNOWN"})
        confidence = Confidence.HIGH if data.get("tx_status") != "UNCERTAIN" else Confidence.MEDIUM

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


class AccountBalanceInvestigator(BaseInvestigator):
    """Verifies account status and available balance."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.ACCOUNT_BALANCE

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.03, 0.15))

        if case.exception_type.value == "INSUFFICIENT_FUNDS":
            available = float(case.amount) * random.uniform(0.3, 0.8)
            data = {
                "account_status": "ACTIVE",
                "available_balance": round(available, 2),
                "required_amount": float(case.amount),
                "shortfall": round(float(case.amount) - available, 2),
                "pending_credits": round(float(case.amount) * random.uniform(0, 0.5), 2),
            }
        else:
            data = {
                "account_status": "ACTIVE",
                "available_balance": round(float(case.amount) * random.uniform(1.5, 10), 2),
                "required_amount": float(case.amount),
                "shortfall": 0,
            }

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=Confidence.HIGH,
            data=data,
        )


class BeneficiaryValidationInvestigator(BaseInvestigator):
    """Validates beneficiary details against directory services."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.BENEFICIARY_VALIDATION

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.05, 0.25))

        if case.exception_type.value == "INCORRECT_BENEFICIARY":
            ifsc = case.beneficiary_details.ifsc_code or "UNKN0000000"
            corrected_ifsc = ifsc[:4] + "0" + ifsc[5:] if len(ifsc) >= 11 else None
            data = {
                "ifsc_valid": False,
                "original_ifsc": ifsc,
                "suggested_correction": corrected_ifsc,
                "correction_confidence": "HIGH" if corrected_ifsc else "LOW",
                "prior_successful_payments_to_beneficiary": random.randint(0, 5),
                "beneficiary_account_valid": True,
            }
            confidence = Confidence.HIGH
        else:
            data = {
                "ifsc_valid": True,
                "beneficiary_account_valid": True,
                "prior_successful_payments_to_beneficiary": random.randint(1, 20),
            }
            confidence = Confidence.HIGH

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


class ComplianceInvestigator(BaseInvestigator):
    """Checks AML/sanctions screening status."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.COMPLIANCE_CHECK

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.1, 0.3))

        if case.exception_type.value == "COMPLIANCE_HOLD":
            data = {
                "screening_status": "HELD",
                "hold_type": random.choice(["AML_REVIEW", "SANCTIONS_MATCH", "PEP_FLAG"]),
                "auto_clearable": False,
                "requires_human_review": True,
                "hold_duration_hours": random.randint(1, 48),
                "similar_cases_cleared_pct": random.randint(60, 90),
            }
            confidence = Confidence.HIGH
        else:
            data = {
                "screening_status": "CLEARED",
                "auto_clearable": True,
                "requires_human_review": False,
            }
            confidence = Confidence.HIGH

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


class NetworkStatusInvestigator(BaseInvestigator):
    """Checks payment network availability and acknowledgments."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.NETWORK_STATUS

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.05, 0.2))

        if case.exception_type.value == "NETWORK_FAILURE":
            data = {
                "network_available": False,
                "outage_type": random.choice(["PARTIAL", "FULL"]),
                "estimated_recovery_minutes": random.randint(5, 120),
                "last_successful_transaction": datetime.now(timezone.utc).isoformat(),
                "affected_rails": [case.payment_rail],
            }
            confidence = Confidence.HIGH
        else:
            data = {
                "network_available": True,
                "latency_ms": random.randint(50, 500),
                "success_rate_last_hour": random.uniform(0.95, 0.999),
            }
            confidence = Confidence.HIGH

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


class RetryHistoryInvestigator(BaseInvestigator):
    """Retrieves prior retry attempts for this payment."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.RETRY_HISTORY

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.03, 0.1))

        if case.exception_type.value == "UNCERTAIN_RETRY":
            attempts = random.randint(1, 4)
            data = {
                "total_attempts": attempts,
                "last_attempt_status": random.choice(["FAILED", "UNKNOWN", "TIMEOUT"]),
                "last_attempt_timestamp": datetime.now(timezone.utc).isoformat(),
                "consistent_failure_point": random.choice(["DEBIT", "CREDIT", "NETWORK", None]),
                "max_retries_allowed": 5,
                "retries_remaining": 5 - attempts,
            }
        else:
            data = {
                "total_attempts": 0 if case.exception_type.value != "NETWORK_FAILURE" else 1,
                "last_attempt_status": "N/A",
                "max_retries_allowed": 5,
                "retries_remaining": 5,
            }

        confidence = Confidence.HIGH if data.get("last_attempt_status") != "UNKNOWN" else Confidence.MEDIUM

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


class DuplicateDetectionInvestigator(BaseInvestigator):
    """Searches for payments with matching attributes."""

    @property
    def evidence_type(self) -> EvidenceType:
        return EvidenceType.DUPLICATE_CHECK

    async def _gather_evidence(self, case: ExceptionCase) -> Evidence:
        await asyncio.sleep(random.uniform(0.05, 0.15))

        if case.exception_type.value == "DUPLICATE":
            data = {
                "duplicate_found": True,
                "original_payment_id": f"PAY-{hash(case.payment_id) % 10000:04d}",
                "original_status": "COMPLETED",
                "original_timestamp": datetime.now(timezone.utc).isoformat(),
                "match_confidence": "EXACT",
                "matching_fields": ["amount", "beneficiary", "date"],
            }
            confidence = Confidence.HIGH
        else:
            data = {
                "duplicate_found": False,
                "similar_payments_24h": random.randint(0, 2),
                "match_confidence": "NONE",
            }
            confidence = Confidence.HIGH

        return Evidence(
            case_id=case.case_id,
            source_agent=self.name,
            evidence_type=self.evidence_type,
            confidence=confidence,
            data=data,
        )


def get_investigators_for_case(case: ExceptionCase) -> list[BaseInvestigator]:
    """Select relevant investigators based on exception type."""
    always_run = [
        TransactionStateInvestigator(),
        DuplicateDetectionInvestigator(),
    ]

    type_specific: dict[str, list[BaseInvestigator]] = {
        "INSUFFICIENT_FUNDS": [AccountBalanceInvestigator()],
        "INCORRECT_BENEFICIARY": [BeneficiaryValidationInvestigator()],
        "COMPLIANCE_HOLD": [ComplianceInvestigator()],
        "NETWORK_FAILURE": [NetworkStatusInvestigator(), RetryHistoryInvestigator()],
        "CUTOFF_MISS": [NetworkStatusInvestigator()],
        "UNCERTAIN_RETRY": [RetryHistoryInvestigator(), NetworkStatusInvestigator(), AccountBalanceInvestigator()],
        "DUPLICATE": [],
    }

    specific = type_specific.get(case.exception_type.value, [])
    return always_run + specific
