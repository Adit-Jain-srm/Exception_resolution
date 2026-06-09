# Payment Exception Resolution Agent — High-Level Architecture

## 1. System Overview

A production-grade multi-agent system that detects payment exceptions, diagnoses root causes using internal and external evidence, determines whether the issue can be resolved automatically or requires escalation, and advances the case through safe remediation with full auditability.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        PAYMENT EXCEPTION RESOLUTION SYSTEM                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐        │
│  │  INGRESS │──▶│ ORCHESTRATOR │──▶│ INVESTIGATION │──▶│   DECISION   │        │
│  │  GATEWAY │   │    AGENT     │   │    AGENTS     │   │    ENGINE    │        │
│  └──────────┘   └──────────────┘   └───────────────┘   └──────┬───────┘        │
│       ▲                                                         │                │
│       │                                                         ▼                │
│  ┌──────────┐                                          ┌──────────────┐         │
│  │ FEEDBACK │◀─────────────────────────────────────────│    EGRESS    │         │
│  │  & REPLAY│                                          │   EXECUTOR   │         │
│  └──────────┘                                          └──────┬───────┘         │
│                                                                │                 │
│                                                                ▼                 │
│                                                       ┌──────────────┐          │
│                                                       │  ASYNC POST  │          │
│                                                       │  DECISION    │          │
│                                                       └──────────────┘          │
│                                                                                  │
├──────────────────────────────────────────────────────────────────────────────────┤
│  CROSS-CUTTING: Audit Log │ Observability │ Config Store │ Safety Controls       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent Catalogue

### 2.1 Ingress Gateway Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Receive exception events from multiple sources, validate schema, normalize payload, deduplicate, and emit a canonical `ExceptionCase` |
| **Inputs** | Raw exception events from payment rails, manual triggers, monitoring alerts |
| **Outputs** | Normalized `ExceptionCase` to orchestrator queue |
| **Contract** | Must be idempotent — same event processed twice yields zero new cases |
| **Authority** | Can reject malformed events; cannot make resolution decisions |

**Key Responsibilities:**
- Schema validation and enrichment
- Deduplication via `payment_id + exception_type + timestamp` composite key
- Normalization across rail-specific formats (SWIFT, ACH, UPI, SEPA)
- Rate limiting and back-pressure signaling
- Dead-letter routing for unparseable events

---

### 2.2 Orchestrator Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Sequence the resolution workflow, manage timeouts, enforce latency budgets, coordinate sub-agents |
| **Inputs** | Normalized `ExceptionCase` from Ingress |
| **Outputs** | Dispatches to Investigation agents; receives evidence; routes to Decision Engine |
| **Contract** | Stateful per-case; must honor SLA timers and escalate on timeout |
| **Authority** | Can parallelize investigations, kill stalled sub-tasks, escalate to human |

**Key Responsibilities:**
- Case state machine management (OPEN → INVESTIGATING → DECIDING → RESOLVED/ESCALATED)
- Latency budget enforcement (e.g., 30s for auto-resolution, 5min for complex cases)
- Parallel fan-out to multiple investigation agents
- Circuit breaker for downstream dependency failures
- Priority queue management (amount-based, client-tier-based)

**State Machine:**
```
RECEIVED → VALIDATING → INVESTIGATING → EVIDENCE_COMPLETE → DECIDING → ACTION_TAKEN → MONITORING → RESOLVED
                                                                    ↘ ESCALATED → HUMAN_REVIEW → RESOLVED
                                                          ↘ HELD → AWAITING_INPUT → DECIDING (re-entry)
```

---

### 2.3 Investigation Agents (Specialist Pool)

A pool of specialized agents, each responsible for gathering evidence from a specific domain:

#### 2.3.1 Transaction State Investigator
- Queries core banking/payment system for current transaction status
- Retrieves debit/credit leg states, hold flags, reversal markers
- Checks for partial execution states

#### 2.3.2 Account & Balance Investigator
- Verifies account status (active, frozen, closed)
- Checks available balance vs. transaction amount
- Identifies holds or encumbrances affecting available funds

#### 2.3.3 Beneficiary Validation Investigator
- Validates beneficiary details against directory services
- Checks IFSC/routing number validity
- Cross-references with prior successful payments to same beneficiary

#### 2.3.4 Compliance & Sanctions Investigator
- Checks AML/sanctions screening status
- Retrieves compliance hold reasons
- Determines if hold is pending human review or auto-clearable

#### 2.3.5 Network & Rail Status Investigator
- Checks payment network availability (SWIFT, NEFT, UPI, ACH)
- Retrieves clearing house acknowledgments/rejections
- Identifies network-wide outages vs. specific transaction failures

#### 2.3.6 Retry History Investigator
- Retrieves prior retry attempts for this payment
- Checks outcomes of previous retries
- Identifies patterns (e.g., consistently failing at same point)

#### 2.3.7 Duplicate Detection Investigator
- Searches for payments with matching attributes (amount, beneficiary, date)
- Determines if current exception is a duplicate trigger
- Checks if original payment already succeeded

**Common Contract for All Investigators:**
- Must return within configurable timeout (default: 5s per investigator)
- Must return structured `Evidence` envelope with confidence score
- Must handle partial/unavailable data gracefully (return `INCONCLUSIVE` not error)
- Must never modify state — read-only operations only

---

### 2.4 Decision Engine Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Evaluate collected evidence, apply resolution rules, determine action with confidence and justification |
| **Inputs** | Evidence bundle from all investigators, case context, configuration rules |
| **Outputs** | `ResolutionDecision` with action, confidence, justification, and risk assessment |
| **Contract** | Deterministic — same evidence set must produce same decision |
| **Authority** | Can decide: RETRY, REPAIR, HOLD, CANCEL, ESCALATE, DEFER |

**Decision Actions:**
| Action | When | Risk Level |
|--------|------|------------|
| `AUTO_RETRY` | Transient failure, no state conflict, within retry window | LOW |
| `REPAIR_AND_RETRY` | Correctable data issue (e.g., IFSC correction) | MEDIUM |
| `HOLD_PENDING_FUNDS` | Insufficient balance, retry after funding window | LOW |
| `HOLD_PENDING_INPUT` | Needs client/ops clarification | LOW |
| `CANCEL_SAFELY` | Duplicate confirmed, or irrecoverable error | MEDIUM |
| `ESCALATE_COMPLIANCE` | Sanctions/AML hold requiring human review | HIGH |
| `ESCALATE_OPERATIONS` | Complex multi-system conflict | MEDIUM |
| `DEFER_TO_NEXT_CYCLE` | Cut-off time miss, re-queue for next window | LOW |

**Decision Rules Engine:**
- Rule-based first pass (deterministic, auditable)
- Confidence scoring (HIGH/MEDIUM/LOW)
- Threshold gates: actions above risk threshold require human approval
- Rail-specific rule sets (different rules for SWIFT vs. UPI vs. ACH)

---

### 2.5 Egress Executor Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Execute the decided action safely against downstream systems |
| **Inputs** | `ResolutionDecision` from Decision Engine |
| **Outputs** | Execution confirmation/failure, side-effect records |
| **Contract** | Idempotent execution — safe to retry on failure |
| **Authority** | Can execute approved actions; cannot deviate from decision |

**Key Responsibilities:**
- Idempotent action execution with deduplication keys
- Pre-execution safety checks (balance re-verification, status re-check)
- Rollback capability on partial failure
- Timeout handling with safe fallback (HOLD rather than corrupt)
- Confirmation receipt collection

---

### 2.6 Async Post-Decision Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Handle follow-on work after primary decision path completes |
| **Inputs** | Decision outcome, execution results |
| **Outputs** | Notifications, case updates, monitoring registrations |
| **Contract** | Eventually consistent; failures here don't block primary flow |
| **Authority** | Can send notifications, update cases, register monitors |

**Key Responsibilities:**
- Client notification dispatch (email, SMS, in-app)
- Operations team alerting for escalated cases
- Retry scheduler registration (with exponential backoff)
- Audit trail persistence
- Metrics emission for observability
- SLA timer management

---

### 2.7 Feedback & Replay Agent

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Incorporate new status events, re-evaluate prior decisions, learn from outcomes |
| **Inputs** | New status events (network acks, retry results, human overrides) |
| **Outputs** | Case re-opening triggers, decision corrections, rule refinements |
| **Contract** | Can re-open resolved cases; must preserve full decision history |
| **Authority** | Can trigger re-investigation; cannot directly execute actions |

**Key Responsibilities:**
- Status event correlation to existing cases
- Decision replay when new evidence arrives
- Human override incorporation
- Outcome tracking for rule refinement
- Closed-loop learning (which auto-decisions succeeded/failed)

---

## 3. Communication Patterns

### 3.1 Inter-Agent Communication

```
┌────────────────────────────────────────────────────────────────────┐
│                     MESSAGE BUS (Event-Driven)                      │
│                                                                      │
│  Topics:                                                             │
│  • exception.ingested        — Ingress → Orchestrator               │
│  • investigation.requested   — Orchestrator → Investigators         │
│  • evidence.collected        — Investigators → Orchestrator         │
│  • decision.requested        — Orchestrator → Decision Engine       │
│  • decision.rendered         — Decision Engine → Orchestrator       │
│  • action.execute            — Orchestrator → Egress Executor       │
│  • action.completed          — Egress → Async Post-Decision         │
│  • status.updated            — External → Feedback Agent            │
│  • case.reopened             — Feedback → Orchestrator              │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Contracts

Every inter-agent message follows a standard envelope:

```json
{
  "message_id": "uuid-v4",
  "correlation_id": "case-uuid",
  "causation_id": "parent-message-uuid",
  "timestamp": "ISO-8601",
  "source_agent": "agent-name",
  "target_agent": "agent-name",
  "payload_type": "schema-reference",
  "payload": { ... },
  "metadata": {
    "retry_count": 0,
    "ttl_ms": 30000,
    "priority": "HIGH"
  }
}
```

---

## 4. Cross-Cutting Concerns

### 4.1 Audit Trail
- Every agent action logged with: who, what, when, why, evidence-used
- Immutable append-only audit log
- Queryable by case_id, payment_id, time range, agent, action type
- Retention: configurable per regulatory requirement (min 7 years)

### 4.2 Observability
- Structured logging (JSON) with correlation IDs
- Distributed tracing (OpenTelemetry) across agent boundaries
- Metrics: case throughput, resolution time P50/P95/P99, auto-resolution rate
- Alerting: SLA breaches, decision confidence drops, error rate spikes

### 4.3 Safety Controls
- Kill switch: disable auto-resolution globally or per rail/exception-type
- Degraded mode: route all cases to human review when confidence drops
- Rate limits: max auto-retries per payment per hour
- Amount thresholds: manual review required above configurable amount
- Circuit breakers: stop calling failed downstream services

### 4.4 Idempotency
- Every action has a unique idempotency key
- Duplicate detection at ingress (event-level) and egress (action-level)
- State checks before execution (prevent double-debit)

### 4.5 Configuration Store
- Rail-specific rules and thresholds
- Client-tier escalation policies
- Retry limits and backoff curves
- Amount-based routing rules
- Feature flags for gradual rollout

---

## 5. Data Model (Core Entities)

```
ExceptionCase {
  case_id: UUID
  payment_id: String
  client_id: String
  account_id: String
  payment_rail: Enum[SWIFT, ACH, UPI, NEFT, SEPA, INTERNAL]
  payment_type: Enum[DOMESTIC, WIRE, BOOK_TRANSFER, DISBURSEMENT]
  exception_type: Enum[INCORRECT_BENEFICIARY, INSUFFICIENT_FUNDS, DUPLICATE, 
                        COMPLIANCE_HOLD, NETWORK_FAILURE, CUTOFF_MISS, UNCERTAIN_RETRY]
  amount: Decimal
  currency: String
  beneficiary_details: JSON
  status: Enum[RECEIVED, INVESTIGATING, DECIDING, ACTION_TAKEN, 
               RESOLVED, ESCALATED, HELD, CANCELLED]
  priority: Enum[CRITICAL, HIGH, MEDIUM, LOW]
  created_at: Timestamp
  updated_at: Timestamp
  sla_deadline: Timestamp
  resolution: Resolution | null
  evidence_bundle: Evidence[]
  decision_history: Decision[]
  audit_trail: AuditEntry[]
}

Evidence {
  evidence_id: UUID
  case_id: UUID
  source_agent: String
  evidence_type: String
  confidence: Enum[HIGH, MEDIUM, LOW, INCONCLUSIVE]
  data: JSON
  collected_at: Timestamp
  ttl: Duration
}

Decision {
  decision_id: UUID
  case_id: UUID
  action: Enum[AUTO_RETRY, REPAIR_AND_RETRY, HOLD_PENDING_FUNDS, 
               HOLD_PENDING_INPUT, CANCEL_SAFELY, ESCALATE_COMPLIANCE,
               ESCALATE_OPERATIONS, DEFER_TO_NEXT_CYCLE]
  confidence: Enum[HIGH, MEDIUM, LOW]
  justification: String
  evidence_used: UUID[]
  rules_applied: String[]
  risk_level: Enum[LOW, MEDIUM, HIGH]
  requires_approval: Boolean
  decided_at: Timestamp
  decided_by: String (agent or human)
}
```

---

## 6. Infrastructure Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INFRASTRUCTURE LAYER                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐     │
│  │   Message    │  │   State     │  │     Configuration       │     │
│  │   Broker     │  │   Store     │  │        Store            │     │
│  │  (Kafka/     │  │  (Postgres  │  │   (Consul/etcd +        │     │
│  │   RabbitMQ)  │  │   + Redis)  │  │    feature flags)       │     │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘     │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐     │
│  │   Audit     │  │ Observability│  │      Scheduler          │     │
│  │   Log       │  │  (OTel +    │  │   (Temporal/             │     │
│  │ (Immutable  │  │  Prometheus │  │    Celery Beat)          │     │
│  │  append)    │  │  + Grafana) │  │                          │     │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Technology Choices:**
| Component | Primary Choice | Rationale |
|-----------|---------------|-----------|
| Workflow Orchestration | Temporal | Durable execution, built-in retry, visibility |
| Message Bus | Apache Kafka | Ordering guarantees, replay capability, high throughput |
| State Store | PostgreSQL | ACID transactions, JSON support, audit-friendly |
| Cache/Locks | Redis | Distributed locks for idempotency, fast lookups |
| Config | etcd + LaunchDarkly | Dynamic config + feature flags |
| Observability | OpenTelemetry + Grafana | Industry standard, vendor-neutral |
| Audit | Immutable append-only Postgres partition | Regulatory compliance |

---

## 7. Deployment Topology

```
                    ┌─────────────────┐
                    │   Load Balancer  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
      ┌───────▼───────┐  ┌──▼──────────┐  ┌▼──────────────┐
      │ Ingress Pods  │  │ API Gateway │  │ Webhook Recv. │
      │  (Stateless)  │  │ (Admin/Ops) │  │  (Status Evts)│
      └───────┬───────┘  └─────────────┘  └───────┬───────┘
              │                                     │
              ▼                                     ▼
      ┌──────────────────────────────────────────────────┐
      │              Kafka / Message Bus                   │
      └──────────────────────────────────────────────────┘
              │
              ▼
      ┌──────────────────────────────────────────────────┐
      │         Temporal Workers (Agent Pool)              │
      │  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
      │  │Orchestrator│ │Investigators│ │Decision Eng. │ │
      │  │  Workers   │ │   Workers   │ │   Workers    │ │
      │  └────────────┘ └────────────┘ └──────────────┘ │
      │  ┌────────────┐ ┌────────────┐                  │
      │  │  Egress    │ │  Feedback  │                  │
      │  │  Workers   │ │  Workers   │                  │
      │  └────────────┘ └────────────┘                  │
      └──────────────────────────────────────────────────┘
```

---

## 8. Security Architecture

- **Network isolation**: Agent-to-agent communication only via message bus (no direct calls)
- **mTLS**: All inter-service communication encrypted
- **Secrets management**: Vault for API keys, connection strings
- **PII handling**: Payment details encrypted at rest, masked in logs
- **Access control**: RBAC for operations UI, per-agent service accounts
- **Data retention**: Configurable per jurisdiction, auto-purge of PII after retention period
