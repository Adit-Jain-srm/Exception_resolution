"""LLM Guardrails — safety layer between LLM output and action execution.

Principle: LLMs ADVISE, deterministic code EXECUTES.
No LLM output directly triggers a financial action without passing through
schema validation, action allowlist, confidence floor, and safety checks.
"""

from __future__ import annotations

import re
import structlog
from decimal import Decimal

from ..models.domain import Decision, Evidence, ExceptionCase
from ..models.enums import Confidence, ResolutionAction, RiskLevel

logger = structlog.get_logger()


class GuardrailViolation(Exception):
    """Raised when LLM output violates a guardrail."""

    def __init__(self, guardrail: str, reason: str, recommendation: str = "ESCALATE") -> None:
        self.guardrail = guardrail
        self.reason = reason
        self.recommendation = recommendation
        super().__init__(f"[{guardrail}] {reason}")


ALLOWED_ACTIONS = set(ResolutionAction)

CONFIDENCE_FLOORS: dict[RiskLevel, Confidence] = {
    RiskLevel.LOW: Confidence.MEDIUM,
    RiskLevel.MEDIUM: Confidence.MEDIUM,
    RiskLevel.HIGH: Confidence.HIGH,
}

CONFIDENCE_RANK = {
    Confidence.HIGH: 3,
    Confidence.MEDIUM: 2,
    Confidence.LOW: 1,
    Confidence.INCONCLUSIVE: 0,
}


class GuardrailPipeline:
    """
    Validates LLM-produced decisions before they can be executed.
    Each guardrail either passes silently or raises GuardrailViolation.
    """

    def __init__(
        self,
        high_value_threshold: Decimal = Decimal("50000"),
        max_llm_calls_per_case: int = 5,
    ) -> None:
        self._high_value_threshold = high_value_threshold
        self._max_llm_calls = max_llm_calls_per_case
        self._violations_count = 0

    @property
    def violations_count(self) -> int:
        return self._violations_count

    async def validate(self, decision: Decision, case: ExceptionCase) -> Decision:
        """Run all guardrails. Returns validated decision or raises GuardrailViolation."""
        checks = [
            self._check_action_allowlist,
            self._check_confidence_floor,
            self._check_evidence_references,
            self._check_amount_threshold,
            self._check_hallucination_markers,
        ]

        for check in checks:
            check(decision, case)

        logger.info("guardrails_passed", case_id=case.case_id, action=decision.action)
        return decision

    def _check_action_allowlist(self, decision: Decision, case: ExceptionCase) -> None:
        """Reject any action not in the predefined enum."""
        if decision.action not in ALLOWED_ACTIONS:
            self._violations_count += 1
            raise GuardrailViolation(
                "ACTION_ALLOWLIST",
                f"Action '{decision.action}' is not in the allowed action set",
            )

    def _check_confidence_floor(self, decision: Decision, case: ExceptionCase) -> None:
        """Reject decisions below minimum confidence for their risk level."""
        min_confidence = CONFIDENCE_FLOORS.get(decision.risk_level, Confidence.MEDIUM)
        if CONFIDENCE_RANK[decision.confidence] < CONFIDENCE_RANK[min_confidence]:
            self._violations_count += 1
            raise GuardrailViolation(
                "CONFIDENCE_FLOOR",
                f"Confidence {decision.confidence} is below minimum "
                f"{min_confidence} for risk level {decision.risk_level}",
                recommendation="ESCALATE_OPERATIONS",
            )

    def _check_evidence_references(self, decision: Decision, case: ExceptionCase) -> None:
        """Detect hallucination: decision references evidence IDs that don't exist."""
        valid_ids = {e.evidence_id for e in case.evidence_bundle}
        invalid_refs = [eid for eid in decision.evidence_used if eid not in valid_ids]

        if invalid_refs:
            self._violations_count += 1
            raise GuardrailViolation(
                "HALLUCINATION_DETECTION",
                f"Decision references non-existent evidence IDs: {invalid_refs}",
            )

    def _check_amount_threshold(self, decision: Decision, case: ExceptionCase) -> None:
        """High-value transactions require approval for non-LOW-risk actions."""
        if case.amount >= self._high_value_threshold:
            if decision.risk_level != RiskLevel.LOW and not decision.requires_approval:
                decision.requires_approval = True
                logger.warning(
                    "high_value_approval_enforced",
                    case_id=case.case_id,
                    amount=float(case.amount),
                )

    def _check_hallucination_markers(self, decision: Decision, case: ExceptionCase) -> None:
        """Check for common LLM hallucination patterns in justification text."""
        markers = [
            r"I think",
            r"I believe",
            r"probably",
            r"might be",
            r"as an AI",
            r"I cannot",
            r"I don't have access",
        ]
        justification_lower = decision.justification.lower()
        for marker in markers:
            if re.search(marker, justification_lower):
                self._violations_count += 1
                raise GuardrailViolation(
                    "HALLUCINATION_MARKERS",
                    f"Justification contains uncertainty marker: '{marker}'. "
                    f"Decisions must be stated factually, not speculatively.",
                )


class PIIMasker:
    """Masks sensitive data before sending to LLM, preserving what's needed for decisions."""

    MASK_PATTERNS = {
        "account_number": r"\d{4,}",
        "name": r"[A-Z][a-z]+ [A-Z][a-z]+",
    }

    @staticmethod
    def mask_for_llm(case: ExceptionCase) -> dict:
        """Return case data with PII masked for LLM consumption."""
        return {
            "case_id": case.case_id,
            "payment_id": case.payment_id,
            "exception_type": case.exception_type,
            "payment_rail": case.payment_rail,
            "amount": float(case.amount),
            "currency": case.currency,
            "beneficiary_ifsc": case.beneficiary_details.ifsc_code,
            "beneficiary_bank": case.beneficiary_details.bank_name,
            "account_id_masked": f"XXXX-{case.account_id[-4:]}" if len(case.account_id) >= 4 else "MASKED",
            "beneficiary_name": "[MASKED]",
            "beneficiary_account": "[MASKED]",
        }

    @staticmethod
    def mask_evidence_for_llm(evidence: list[Evidence]) -> list[dict]:
        """Return evidence bundle with PII stripped."""
        masked = []
        for e in evidence:
            masked_data = {k: v for k, v in e.data.items() if k not in ("account_number", "name", "ssn", "pan")}
            masked.append({
                "evidence_id": e.evidence_id,
                "type": e.evidence_type,
                "confidence": e.confidence,
                "data": masked_data,
            })
        return masked
