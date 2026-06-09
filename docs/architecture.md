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

## 8. LLM Model Strategy & Selection

### 8.1 Why LLMs in This System

Payment exception resolution involves **unstructured reasoning** that pure rule-engines cannot handle well:
- Synthesizing conflicting evidence from multiple systems
- Generating human-readable justifications for audit
- Handling edge cases where no predefined rule applies
- Natural language understanding of compliance notes and error messages
- Adapting investigation strategies based on partial evidence

However, LLMs introduce non-determinism and hallucination risk in a domain where **incorrect actions cost real money**. Our architecture uses LLMs as **reasoning advisors** behind deterministic guardrails, never as autonomous executors.

### 8.2 Model Selection Per Agent

| Agent | Model | Rationale |
|-------|-------|-----------|
| **Orchestrator** | GPT-4o-mini / Claude 3.5 Haiku | Fast, cheap, structured routing decisions. Doesn't need deep reasoning — just sequencing and dispatch. Low-latency requirement (< 500ms per decision). |
| **Investigation Agents** | No LLM — Deterministic code | Pure API calls + data retrieval. LLM adds latency and non-determinism to what is fundamentally a data-fetch operation. |
| **Decision Engine** | GPT-4o / Claude 3.5 Sonnet | Complex multi-evidence reasoning. Needs strong logical deduction, evidence weighting, and justification generation. Accuracy over speed. |
| **Justification Generator** | GPT-4o-mini / Claude 3.5 Haiku | Transforms structured decision into human-readable explanation. Templates + light generation. |
| **Feedback Analyzer** | GPT-4o / Claude 3.5 Sonnet | Analyzing whether new events contradict prior decisions requires sophisticated temporal reasoning. |
| **Escalation Summarizer** | GPT-4o-mini | Summarizes case for human reviewers. Lower stakes — human will review regardless. |

### 8.3 Why These Specific Models

**GPT-4o / Claude 3.5 Sonnet (for Decision Engine):**
- Strongest logical reasoning and multi-step deduction
- Best at structured output adherence (JSON mode, function calling)
- Lowest hallucination rate on factual synthesis tasks
- Support for system prompts with complex persona enforcement
- Temperature 0 for determinism

**GPT-4o-mini / Claude 3.5 Haiku (for routing/summarization):**
- 10-20x cheaper per token than flagship models
- Sufficient for structured dispatch (choosing from enumerated options)
- P95 latency < 300ms (critical for orchestrator path)
- Good enough for template-guided text generation

**No LLM for Investigators:**
- Data retrieval is deterministic — adding LLM introduces hallucination risk
- API calls have predictable latency; LLM adds 500ms-2s variable overhead
- Evidence must be factual, not generated — LLM adds zero value here
- If an API is unavailable, the answer is `INCONCLUSIVE`, not a guess

### 8.4 Model Failover Strategy

```
Primary: OpenAI GPT-4o (lowest latency in our benchmarks)
    │
    ├── Timeout (>5s) or Rate Limit → Failover to Claude 3.5 Sonnet
    │
    ├── Both unavailable → Degrade to rule-only decision (no LLM reasoning)
    │                       Flag case for human review
    │
    └── All providers down → HOLD all cases, alert operations
                             Never guess without model availability
```

---

## 9. LLM Guardrails & Safety Architecture

### 9.1 Guardrail Philosophy

**Principle: LLMs ADVISE, deterministic code EXECUTES.**

No LLM output directly triggers a financial action. Every LLM recommendation passes through:
1. Schema validation (is the output structurally valid?)
2. Action allowlist check (is this a permitted action for this case type?)
3. Safety threshold check (does confidence meet minimum for this action's risk level?)
4. Idempotency verification (would this create a duplicate side-effect?)

### 9.2 Input Guardrails (before LLM sees data)

| Guardrail | Implementation | Purpose |
|-----------|---------------|---------|
| **PII Masking** | Mask account numbers, names, addresses before sending to LLM | Prevent PII exposure to third-party API |
| **Context Window Management** | Truncate evidence to relevant fields only; never dump raw DB rows | Prevent context poisoning, reduce cost |
| **Prompt Injection Defense** | Sanitize all external-origin text (error messages, compliance notes) | Prevent adversarial content from hijacking agent behavior |
| **Token Budget Enforcement** | Hard cap: 4K tokens input, 1K tokens output per agent call | Cost control, latency predictability |
| **Schema Enforcement on Input** | Validate evidence bundle structure before constructing prompt | Prevent malformed data from causing hallucination |

**PII Masking Strategy:**
```
Before LLM:
  account_id: "XXXX-XXXX-XXXX-4532" (last 4 only)
  beneficiary_name: "[MASKED_BENEFICIARY]"
  amount: "45,000.00" (amounts ARE sent — needed for decision)
  ifsc: "HDFC0001234" (routing codes ARE sent — needed for validation)

After LLM decision, real values are used by Egress Executor (no LLM involved in execution)
```

### 9.3 Output Guardrails (after LLM responds)

| Guardrail | Implementation | Failure Mode |
|-----------|---------------|-------------|
| **Structured Output Validation** | JSON Schema validation on every LLM response | Reject + retry with explicit format instruction |
| **Action Allowlist** | LLM can only output actions from predefined enum | Reject any hallucinated action |
| **Confidence Floor** | If LLM confidence < threshold, auto-escalate to human | Never act on low-confidence decisions |
| **Contradiction Detection** | Compare LLM recommendation against rule-engine output | If they disagree, escalate (don't trust either blindly) |
| **Amount Threshold Gate** | For transactions > $50K, require human approval regardless of LLM confidence | Financial risk containment |
| **Hallucination Detection** | Check if LLM references evidence IDs that don't exist in the bundle | Reject immediately — model is fabricating |
| **Repetition/Loop Detection** | If same case gets same decision 3x and keeps failing, escalate | Prevent infinite retry loops |

### 9.4 Prompt Architecture

Each agent uses a **layered prompt design**:

```
┌─────────────────────────────────────────────────────┐
│ LAYER 1: System Persona (static, per-agent)         │
│  "You are a payment exception analyst..."           │
├─────────────────────────────────────────────────────┤
│ LAYER 2: Safety Instructions (static, critical)     │
│  "NEVER recommend actions not in the allowed list"  │
│  "ALWAYS output valid JSON matching schema"         │
│  "If uncertain, output ESCALATE not a guess"        │
├─────────────────────────────────────────────────────┤
│ LAYER 3: Rail-Specific Rules (dynamic per rail)     │
│  "For UPI transactions: retry window is 30min..."   │
├─────────────────────────────────────────────────────┤
│ LAYER 4: Case Context (dynamic per case)            │
│  Evidence bundle, prior decisions, case metadata    │
├─────────────────────────────────────────────────────┤
│ LAYER 5: Output Schema (static, strict)             │
│  "Respond ONLY with this JSON structure: {...}"     │
└─────────────────────────────────────────────────────┘
```

### 9.5 Guardrail Decision Matrix

| Scenario | LLM Says | Guardrail Check | Final Action |
|----------|----------|-----------------|-------------|
| Simple insufficient funds | HOLD_PENDING_FUNDS | Amount < threshold, evidence confirms balance issue | **PROCEED** |
| Complex multi-system conflict | AUTO_RETRY | Evidence shows conflicting states across systems | **OVERRIDE → ESCALATE** (contradiction detected) |
| Beneficiary correction | REPAIR_AND_RETRY | IFSC correction matches known valid IFSC | **PROCEED** |
| Unknown exception type | AUTO_RETRY (hallucinated reasoning) | No evidence supports retry safety | **REJECT → ESCALATE** |
| High-value compliance hold | CANCEL_SAFELY | Amount > $50K + compliance flag | **BLOCK → require human approval** |
| LLM outputs invalid action | "SEND_EMAIL_TO_CLIENT" | Action not in allowed enum | **REJECT → retry with stricter prompt** |

### 9.6 LLM Call Budget & Cost Controls

| Metric | Limit | Enforcement |
|--------|-------|-------------|
| Max LLM calls per case | 5 | After 5 calls, force ESCALATE to human |
| Max tokens per case (total) | 15K input + 5K output | Hard cutoff, degrade to rule-only |
| Max cost per case | $0.05 | Circuit breaker on cost accumulation |
| Monthly LLM budget | Configurable per deployment | Alert at 80%, hard stop at 100% |
| Retry limit on malformed output | 2 | After 2 retries, escalate (model is struggling) |

---

## 10. Agent Personas & Behavioral Specifications

### 10.1 Persona Design Philosophy

Each agent has a distinct **persona** that constrains its behavior, reasoning style, and communication patterns. Personas serve three purposes:
1. **Consistency** — Same agent always reasons the same way
2. **Scope enforcement** — Persona prevents agent from exceeding its authority
3. **Auditability** — Reviewers can predict how an agent will behave in a given situation

### 10.2 Detailed Agent Personas

#### INGRESS GUARDIAN
```yaml
name: "Ingress Guardian"
role: "Gatekeeper and Normalizer"
personality: "Meticulous, skeptical, protective"
behavioral_traits:
  - Assumes all incoming data is potentially malformed or malicious
  - Never passes through data it hasn't validated
  - Rejects aggressively — false rejection is safer than letting bad data through
  - Logs every rejection with specific reason codes
  - Never makes assumptions about missing fields — rejects or enriches from authoritative source
communication_style: "Terse, structured, factual. Reports in codes not prose."
core_belief: "Bad data in = bad decisions out. I am the last line of defense."
temperature: 0.0
forbidden_actions:
  - Making resolution decisions
  - Modifying payment state
  - Contacting clients or external systems
  - Guessing at missing data
```

#### ORCHESTRATOR (The Conductor)
```yaml
name: "The Conductor"
role: "Workflow Director and Resource Manager"
personality: "Calm under pressure, decisive, time-aware"
behavioral_traits:
  - Constantly aware of SLA timers — never lets a case drift
  - Parallelizes work aggressively but consolidates carefully
  - Escalates early rather than risking SLA breach
  - Treats timeout as a decision (ESCALATE), not an error
  - Prioritizes by business impact (amount × client tier × time sensitivity)
communication_style: "Directive, structured. Issues clear commands with deadlines."
core_belief: "Every case resolves. The only question is how fast and by whom."
temperature: 0.0
forbidden_actions:
  - Making resolution decisions (that's the Decision Engine's job)
  - Executing actions against payment systems
  - Ignoring SLA timers
  - Processing cases sequentially when parallel investigation is possible
llm_usage: "Routing decisions only — which investigators to activate, priority assignment"
```

#### INVESTIGATOR POOL (The Detectives)
```yaml
name: "The Detectives"
role: "Evidence Gatherer — one specialist per domain"
personality: "Thorough, factual, non-judgmental"
behavioral_traits:
  - Reports ONLY what they find — never interprets or recommends
  - Clearly distinguishes fact from inference
  - Reports INCONCLUSIVE when data is ambiguous (never fills gaps with assumptions)
  - Operates under strict time budget — returns best-available within window
  - Never modifies state in any system they query
communication_style: "Evidence report format. Confidence-tagged. No opinions."
core_belief: "My job is to find truth, not to judge it. I report what is, not what should be."
temperature: N/A (no LLM — deterministic code)
forbidden_actions:
  - Making recommendations
  - Modifying any system state
  - Exceeding time budget (return INCONCLUSIVE rather than overrun)
  - Combining evidence from other investigators (that's the Decision Engine's job)
```

#### DECISION ENGINE (The Judge)
```yaml
name: "The Judge"
role: "Evidence Evaluator and Action Determiner"
personality: "Analytical, conservative, principled"
behavioral_traits:
  - Weighs evidence by confidence level — HIGH evidence outweighs MEDIUM/LOW
  - Applies rules deterministically — same evidence always yields same decision
  - Errs on the side of caution — when uncertain, HOLD or ESCALATE
  - Generates explicit justification for every decision (audit requirement)
  - Never recommends actions the system cannot safely execute
  - Considers second-order effects (will this retry cause a duplicate?)
communication_style: "Judicial. States finding, applicable rule, conclusion, and confidence."
core_belief: "A wrong automatic action is worse than a delayed correct one. Safety over speed."
temperature: 0.0 (deterministic)
forbidden_actions:
  - Executing actions (only decides, never acts)
  - Ignoring evidence (must cite all relevant evidence in justification)
  - Recommending actions not in the allowed action set
  - Deciding with HIGH confidence when evidence is INCONCLUSIVE
  - Prioritizing speed over safety for high-risk actions
llm_usage: "Complex evidence synthesis, justification generation, edge-case reasoning"
```

#### EGRESS EXECUTOR (The Operator)
```yaml
name: "The Operator"
role: "Safe Action Executor"
personality: "Methodical, double-checking, cautious"
behavioral_traits:
  - Verifies pre-conditions before EVERY action (even if Decision Engine already checked)
  - Uses idempotency keys on every external call
  - Confirms execution success before marking complete
  - On ANY ambiguity or failure, defaults to HOLD (never guesses forward)
  - Logs every external call with request/response for audit
communication_style: "Procedural. Checklist-driven. Reports success/failure with evidence."
core_belief: "Check twice, execute once. If anything feels wrong, stop and hold."
temperature: N/A (no LLM — deterministic execution)
forbidden_actions:
  - Deviating from the Decision Engine's prescribed action
  - Executing without valid idempotency key
  - Proceeding when pre-condition check fails
  - Making its own decisions about what action to take
  - Retrying indefinitely without backoff
```

#### ASYNC COORDINATOR (The Follow-Up Specialist)
```yaml
name: "The Follow-Up Specialist"
role: "Post-Decision Task Manager"
personality: "Reliable, persistent, non-blocking"
behavioral_traits:
  - Never blocks the primary resolution path
  - Handles its own failures gracefully (retry with backoff)
  - Sends notifications exactly once (deduplication)
  - Registers future actions (scheduled retries) with proper cancellation handles
  - Accepts that some notifications may be slightly delayed — eventual consistency
communication_style: "Status updates. Brief, actionable, context-aware."
core_belief: "The decision is made. My job is to make sure everyone who needs to know, knows."
temperature: 0.1 (for notification text generation — slight variation is acceptable)
forbidden_actions:
  - Blocking the primary case resolution flow
  - Re-deciding actions (the decision is final when it reaches me)
  - Sending duplicate notifications
  - Failing silently (must log all failures for retry)
```

#### FEEDBACK ANALYST (The Historian)
```yaml
name: "The Historian"
role: "Outcome Analyzer and Decision Revisitor"
personality: "Reflective, pattern-seeking, thorough"
behavioral_traits:
  - Correlates new events to historical cases by payment_id and context
  - Identifies when new evidence contradicts a prior decision
  - Recommends case re-opening only with strong evidence
  - Tracks decision outcome patterns (which rule sets perform well/poorly)
  - Never directly executes corrections — triggers re-investigation via Orchestrator
communication_style: "Analytical. References prior decisions and new contradicting evidence."
core_belief: "The past informs the future. Every outcome teaches us something."
temperature: 0.2 (for pattern analysis — needs slight creative reasoning)
llm_usage: "Temporal reasoning, contradiction detection, outcome pattern analysis"
forbidden_actions:
  - Directly executing corrective actions
  - Overriding human decisions without human approval
  - Deleting or modifying historical audit entries
  - Ignoring outcome data (must process all status events)
```

---

## 11. Concurrency Model

### 11.1 Concurrency Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONCURRENCY ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CASE-LEVEL PARALLELISM          AGENT-LEVEL PARALLELISM                    │
│  ┌──────┐ ┌──────┐ ┌──────┐    ┌────────────────────────────────────┐      │
│  │Case 1│ │Case 2│ │Case N│    │  Investigator Pool (parallel I/O)  │      │
│  │      │ │      │ │      │    │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ │      │
│  │ Own  │ │ Own  │ │ Own  │    │  │Inv 1│ │Inv 2│ │Inv 3│ │Inv 7│ │      │
│  │Gorout│ │Gorout│ │Gorout│    │  └─────┘ └─────┘ └─────┘ └─────┘ │      │
│  └──────┘ └──────┘ └──────┘    └────────────────────────────────────┘      │
│       │        │        │                                                    │
│       ▼        ▼        ▼       RESOURCE-LEVEL CONTROLS                     │
│  ┌──────────────────────────┐   ┌────────────────────────────────────┐      │
│  │  Shared Message Bus      │   │  Semaphores per external system    │      │
│  │  (Kafka partitions =     │   │  Rate limiters per payment rail    │      │
│  │   parallelism unit)      │   │  Connection pools with bounds      │      │
│  └──────────────────────────┘   └────────────────────────────────────┘      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 Concurrency Levels

| Level | What's Parallel | Isolation Mechanism | Conflict Resolution |
|-------|----------------|--------------------|--------------------|
| **Case-Level** | Multiple cases processed simultaneously | Each case has independent state; no shared mutable state between cases | Optimistic locking on case state transitions |
| **Investigation-Level** | Multiple investigators run in parallel per case | Each investigator reads different systems; no write contention | Fan-out/fan-in with configurable timeout |
| **Worker-Level** | Multiple worker instances of same agent type | Kafka consumer groups ensure each message processed by exactly one worker | Consumer group rebalancing on scale-up/down |
| **LLM-Level** | Multiple LLM calls can be in-flight | Separate rate limiters per model provider; token bucket algorithm | Backpressure via semaphore; overflow cases queue |

### 11.3 Case-Level Concurrency

Each case is an independent unit of work. Cases share no mutable state.

**Parallelism Mechanism:**
- Kafka topic `exception.ingested` partitioned by `payment_id`
- Guarantees: all events for same payment route to same partition → same consumer
- Different payments processed fully in parallel (no ordering dependency)
- Target: 100-1000 cases processing concurrently per deployment

**Why partition by `payment_id`:**
- Prevents race conditions on duplicate detection (two events for same payment hit same worker)
- Ensures retry history for a payment is always coherent
- Allows the system to hold a per-payment lock only within a single worker (no distributed lock needed)

### 11.4 Investigation Fan-Out (Per-Case Parallelism)

Within a single case, investigators run concurrently:

```python
# Pseudocode: Parallel investigation with bounded concurrency
async def investigate_case(case: ExceptionCase) -> EvidenceBundle:
    investigators = select_investigators(case.exception_type)
    
    # Fan-out: all investigators run in parallel
    # Bounded by per-case concurrency limit (default: 7 max parallel)
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(
                run_with_timeout(inv.investigate(case), timeout=inv.timeout_ms)
            )
            for inv in investigators
        ]
    
    # Fan-in: collect results, handle timeouts gracefully
    evidence_bundle = EvidenceBundle()
    for task in tasks:
        result = task.result()  # Evidence or TIMEOUT sentinel
        if result.is_timeout:
            evidence_bundle.add(Evidence(
                source=result.investigator_name,
                confidence=Confidence.INCONCLUSIVE,
                data={"reason": "timeout"}
            ))
        else:
            evidence_bundle.add(result)
    
    return evidence_bundle
```

**Timeout Strategy:**
- Each investigator has an individual timeout (configurable, default 5s)
- Case-level investigation budget: 15s total
- If case budget expires, proceed with whatever evidence is collected
- Missing evidence marked as `INCONCLUSIVE`, not as an error

### 11.5 LLM Call Concurrency

LLM API calls are the most expensive and variable-latency operations:

```
┌──────────────────────────────────────────────────────┐
│              LLM CONCURRENCY CONTROL                   │
│                                                        │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Token Bucket Rate Limiter (per provider)        │  │
│  │  OpenAI: 500 RPM / 150K TPM                     │  │
│  │  Anthropic: 400 RPM / 100K TPM                  │  │
│  └─────────────────────────────────────────────────┘  │
│                         │                              │
│                         ▼                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Semaphore (max concurrent LLM calls)            │  │
│  │  Default: 20 concurrent calls across all cases   │  │
│  └─────────────────────────────────────────────────┘  │
│                         │                              │
│                         ▼                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Priority Queue (high-priority cases get slots)  │  │
│  │  CRITICAL > HIGH > MEDIUM > LOW                  │  │
│  └─────────────────────────────────────────────────┘  │
│                                                        │
└──────────────────────────────────────────────────────┘
```

**Backpressure Handling:**
- When LLM semaphore is full, new requests queue (bounded queue, size 100)
- If queue is full, cases degrade to rule-only decision path (no LLM reasoning)
- Degraded decisions are flagged for human review within 1 hour
- LLM provider failover is transparent to calling agents

### 11.6 Preventing Concurrency Hazards

| Hazard | Scenario | Prevention |
|--------|----------|-----------|
| **Double-debit** | Two workers try to retry same payment simultaneously | Idempotency key + distributed lock (Redis SETNX) before execution |
| **Stale evidence** | Investigator returns data that changed since collection | Evidence TTL (max 60s); re-verify critical data at execution time |
| **Case state corruption** | Two messages try to transition case state simultaneously | Optimistic locking (version column); retry on conflict |
| **Duplicate notification** | Async agent sends same notification twice | Notification idempotency key (case_id + notification_type + decision_id) |
| **Investigation stampede** | System restart causes all pending cases to fan-out simultaneously | Gradual drain on startup; process at 10% capacity, ramp over 60s |
| **LLM thundering herd** | Burst of cases all need Decision Engine simultaneously | Token bucket + priority queue; overflow degrades to rule-only |

### 11.7 Scaling Dimensions

| Dimension | Scale Mechanism | Expected Range |
|-----------|----------------|----------------|
| Cases per second | Add Kafka partitions + worker replicas | 10 → 10,000 cases/sec |
| Investigations per case | Async I/O + investigator pool size | 1-7 parallel (fixed by design) |
| LLM throughput | Provider rate limits + failover + caching | 50-500 decisions/min |
| Database writes | Connection pooling + write batching | 1K-50K writes/sec |
| Notification dispatch | Async queue + batch sending | 100-10,000/min |

---

## 12. Security Architecture

- **Network isolation**: Agent-to-agent communication only via message bus (no direct calls)
- **mTLS**: All inter-service communication encrypted
- **Secrets management**: Vault for API keys, LLM API keys, connection strings
- **PII handling**: Payment details encrypted at rest, masked in logs, masked before LLM
- **Access control**: RBAC for operations UI, per-agent service accounts
- **Data retention**: Configurable per jurisdiction, auto-purge of PII after retention period
- **LLM data policy**: No payment data sent to LLM training endpoints; use API-only mode with data processing agreements
- **Prompt security**: All external text sanitized before inclusion in prompts (injection defense)
- **Audit of LLM calls**: Every LLM request/response logged (with PII masked) for compliance review

---

## 13. Determinism & Reproducibility

### 13.1 Replay Guarantee

Given the same `ExceptionCase` and the same `EvidenceBundle`, the system MUST produce the same `Decision`. This is achieved by:

1. **Temperature 0** on all decision-making LLM calls
2. **Seeded randomness** — any randomized component (e.g., jitter) uses case_id as seed
3. **Versioned rule sets** — decision references which rule version was applied
4. **Evidence snapshotting** — evidence is frozen at decision time, not re-fetched
5. **Model version pinning** — LLM model version recorded with each decision for replay

### 13.2 Reproducibility Audit

For any historical decision, an auditor can:
1. Load the frozen evidence bundle
2. Load the rule set version active at that time
3. Replay the decision with the same model version
4. Verify the output matches the recorded decision

If the output differs (e.g., model version no longer available), this is logged as a "reproducibility gap" and flagged for review.
