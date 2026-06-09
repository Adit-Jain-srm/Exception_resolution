"""Core domain models for the payment exception resolution system."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from .enums import (
    CaseStatus,
    Confidence,
    EvidenceType,
    ExceptionType,
    PaymentRail,
    PaymentType,
    Priority,
    ResolutionAction,
    RiskLevel,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class BeneficiaryDetails(BaseModel):
    name: str | None = None
    account_number: str | None = None
    ifsc_code: str | None = None
    routing_number: str | None = None
    bank_name: str | None = None
    upi_id: str | None = None


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=_new_id)
    case_id: str
    source_agent: str
    evidence_type: EvidenceType
    confidence: Confidence
    data: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=_utc_now)
    ttl_seconds: int = 60


class Decision(BaseModel):
    decision_id: str = Field(default_factory=_new_id)
    case_id: str
    action: ResolutionAction
    confidence: Confidence
    justification: str
    evidence_used: list[str] = Field(default_factory=list)
    rules_applied: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    requires_approval: bool = False
    decided_at: datetime = Field(default_factory=_utc_now)
    decided_by: str = "decision_engine"


class AuditEntry(BaseModel):
    entry_id: str = Field(default_factory=_new_id)
    case_id: str
    timestamp: datetime = Field(default_factory=_utc_now)
    agent: str
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class ExceptionCase(BaseModel):
    case_id: str = Field(default_factory=_new_id)
    payment_id: str
    client_id: str
    account_id: str
    payment_rail: PaymentRail
    payment_type: PaymentType
    exception_type: ExceptionType
    amount: Decimal
    currency: str = "INR"
    beneficiary_details: BeneficiaryDetails = Field(default_factory=BeneficiaryDetails)
    status: CaseStatus = CaseStatus.RECEIVED
    priority: Priority = Priority.MEDIUM
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    sla_deadline: datetime | None = None
    evidence_bundle: list[Evidence] = Field(default_factory=list)
    decision_history: list[Decision] = Field(default_factory=list)
    audit_trail: list[AuditEntry] = Field(default_factory=list)
    version: int = 1
    idempotency_key: str | None = None

    def add_evidence(self, evidence: Evidence) -> None:
        self.evidence_bundle.append(evidence)
        self.updated_at = _utc_now()

    def add_decision(self, decision: Decision) -> None:
        self.decision_history.append(decision)
        self.updated_at = _utc_now()

    def add_audit(self, agent: str, action: str, details: dict[str, Any] | None = None) -> None:
        entry = AuditEntry(
            case_id=self.case_id,
            agent=agent,
            action=action,
            details=details or {},
        )
        self.audit_trail.append(entry)
        self.updated_at = _utc_now()


class MessageEnvelope(BaseModel):
    """Standard envelope for all inter-agent communication."""

    message_id: str = Field(default_factory=_new_id)
    correlation_id: str
    causation_id: str | None = None
    timestamp: datetime = Field(default_factory=_utc_now)
    source_agent: str
    target_agent: str
    payload_type: str
    payload: dict[str, Any]
    metadata: MessageMetadata = Field(default_factory=lambda: MessageMetadata())


class MessageMetadata(BaseModel):
    retry_count: int = 0
    ttl_ms: int = 30000
    priority: Priority = Priority.MEDIUM
