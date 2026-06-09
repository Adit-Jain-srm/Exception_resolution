# Payment Exception Resolution Agent — Development Plan

## Project Overview

**Goal**: Build a production-grade multi-agent system for diagnosing, routing, and resolving failed payment transactions end-to-end.

**Track**: Agentic AI / AI Engineering

**Timeline**: 4 phases across ~6-8 weeks (hackathon-adjusted: MVP in Phase 1-2)

---

## Phase 1: Foundation & Core Pipeline (Week 1-2)

### Milestone: A single exception can flow from ingress to decision with stubbed dependencies

### 1.1 Project Scaffolding
- [ ] Initialize Python project with Poetry/uv for dependency management
- [ ] Set up project structure:
  ```
  src/
    agents/           — Agent implementations
    models/           — Pydantic data models
    rules/            — Decision rules engine
    infrastructure/   — Message bus, state store, config
    api/              — REST API for operations
  tests/
    unit/
    integration/
    e2e/
  config/             — Rail-specific configs, thresholds
  docs/               — Architecture, traces, runbooks
  ```
- [ ] Configure linting (ruff), formatting (black), type checking (mypy)
- [ ] Set up Docker Compose for local development stack
- [ ] Initialize git repository with conventional commits

### 1.2 Data Models & Contracts
- [ ] Define `ExceptionCase` Pydantic model with all fields
- [ ] Define `Evidence` model with confidence scoring
- [ ] Define `Decision` model with action enum and justification
- [ ] Define `AuditEntry` model for immutable logging
- [ ] Define inter-agent message envelope schema
- [ ] Create JSON Schema exports for contract validation
- [ ] Write model serialization/deserialization tests

### 1.3 State Management
- [ ] Set up PostgreSQL schema for case storage
- [ ] Implement case repository with CRUD operations
- [ ] Implement case state machine with valid transitions
- [ ] Add optimistic locking for concurrent case updates
- [ ] Implement idempotency key storage (Redis)
- [ ] Write state transition tests

### 1.4 Ingress Gateway Agent
- [ ] Implement event receiver (REST endpoint + message consumer)
- [ ] Build schema validation pipeline
- [ ] Implement payload normalization (rail-specific → canonical)
- [ ] Build deduplication logic (composite key check)
- [ ] Implement dead-letter routing for invalid events
- [ ] Add rate limiting
- [ ] Write unit + integration tests

### 1.5 Orchestrator Agent (Basic)
- [ ] Implement case state machine driver
- [ ] Build sequential workflow: receive → investigate → decide
- [ ] Add timeout management (per-step budgets)
- [ ] Implement basic priority queue (FIFO with priority lanes)
- [ ] Write orchestration flow tests

---

## Phase 2: Investigation & Decision Engine (Week 2-3)

### Milestone: System can auto-resolve simple cases (insufficient funds, duplicate) and escalate complex ones

### 2.1 Investigation Agent Framework
- [ ] Define `BaseInvestigator` abstract class with standard interface
- [ ] Implement evidence collection timeout handling
- [ ] Build parallel investigation dispatcher
- [ ] Implement circuit breaker for external service calls
- [ ] Create `EvidenceBundle` aggregator

### 2.2 Implement Core Investigators
- [ ] **Transaction State Investigator** — query payment status (stubbed/mocked)
- [ ] **Account & Balance Investigator** — verify account state and funds
- [ ] **Beneficiary Validation Investigator** — validate routing details
- [ ] **Duplicate Detection Investigator** — find matching payments
- [ ] **Network Status Investigator** — check rail availability
- [ ] **Retry History Investigator** — retrieve prior attempts
- [ ] **Compliance Investigator** — check hold status
- [ ] Write per-investigator tests with mocked dependencies

### 2.3 Decision Engine
- [ ] Design rule-based decision framework (configurable rules)
- [ ] Implement exception-type-specific rule sets:
  - Insufficient funds → HOLD_PENDING_FUNDS
  - Duplicate confirmed → CANCEL_SAFELY
  - Beneficiary error + auto-correctable → REPAIR_AND_RETRY
  - Network outage + transient → AUTO_RETRY with backoff
  - Compliance hold → ESCALATE_COMPLIANCE
  - Cut-off miss → DEFER_TO_NEXT_CYCLE
  - Uncertain retry → investigate further or ESCALATE
- [ ] Implement confidence scoring based on evidence quality
- [ ] Add risk assessment (amount thresholds, client tier)
- [ ] Implement determinism guarantee (same input → same output)
- [ ] Build justification generator (human-readable explanations)
- [ ] Write decision rule tests with evidence fixtures

### 2.4 Egress Executor Agent
- [ ] Implement action executor with idempotency keys
- [ ] Build pre-execution safety checks
- [ ] Implement retry action (with duplicate guard)
- [ ] Implement hold action (update case status)
- [ ] Implement cancel action (safe reversal trigger)
- [ ] Implement escalation action (route to queue)
- [ ] Add rollback on partial failure
- [ ] Write execution tests

---

## Phase 3: Async Operations, Feedback & Observability (Week 3-5)

### Milestone: Full end-to-end flow with notifications, retry scheduling, replay, and monitoring

### 3.1 Async Post-Decision Agent
- [ ] Implement notification dispatcher (email/SMS stubs)
- [ ] Build retry scheduler (exponential backoff with jitter)
- [ ] Implement SLA timer management
- [ ] Add case status update broadcaster
- [ ] Implement metrics emission

### 3.2 Feedback & Replay Agent
- [ ] Implement status event correlation (match new events to open cases)
- [ ] Build decision replay engine (re-evaluate with new evidence)
- [ ] Handle human override incorporation
- [ ] Implement case re-opening logic
- [ ] Build outcome tracking (decision success/failure rates)
- [ ] Write replay scenario tests

### 3.3 Observability Stack
- [ ] Integrate OpenTelemetry for distributed tracing
- [ ] Add structured logging with correlation IDs to all agents
- [ ] Define and emit key metrics:
  - Case throughput (cases/minute)
  - Resolution time (P50, P95, P99)
  - Auto-resolution rate (% resolved without human)
  - Confidence distribution
  - Error rate by agent
- [ ] Create Grafana dashboards (or dashboard configs)
- [ ] Set up alerting rules (SLA breach, error spike, low confidence)

### 3.4 Audit Trail
- [ ] Implement immutable audit log writer
- [ ] Add audit entries at every decision point
- [ ] Build audit query API (by case, payment, time range)
- [ ] Implement audit trail replay viewer
- [ ] Write audit completeness tests

---

## Phase 4: Production Hardening & Deliverables (Week 5-8)

### Milestone: Production-ready system with full documentation and sample traces

### 4.1 Safety Controls
- [ ] Implement global kill switch (disable auto-resolution)
- [ ] Add per-rail and per-exception-type kill switches
- [ ] Implement degraded mode (all cases → human review)
- [ ] Add amount-based routing (high-value → manual review)
- [ ] Implement rate limits (max retries per payment per hour)
- [ ] Build circuit breaker dashboard

### 4.2 Configuration Management
- [ ] Externalize all thresholds and rules to config files
- [ ] Implement hot-reload for rule changes
- [ ] Add per-rail configuration profiles
- [ ] Build configuration validation on startup
- [ ] Document all configurable parameters

### 4.3 End-to-End Testing
- [ ] Build E2E test harness with simulated payment environment
- [ ] Create test scenarios for all 7 exception types
- [ ] Implement chaos testing (agent failures, timeouts, partial data)
- [ ] Performance test: measure P99 latency under load
- [ ] Idempotency test: replay same events, verify no duplicate actions

### 4.4 Sample End-to-End Traces
- [ ] **Trace 1**: Insufficient funds → auto-hold → funds arrive → auto-retry → resolved
- [ ] **Trace 2**: Duplicate payment → detected → cancelled safely → client notified
- [ ] **Trace 3**: Incorrect IFSC → auto-corrected → retry → success
- [ ] **Trace 4**: Compliance hold → escalated → human approves → released
- [ ] **Trace 5**: Network outage → retry with backoff → succeeds on 3rd attempt
- [ ] **Trace 6**: Cut-off miss → deferred → re-queued for next cycle → processed
- [ ] **Trace 7**: Uncertain retry → investigation → found duplicate risk → held → human review
- [ ] Document each trace with timing, decisions, and evidence used

### 4.5 Documentation Deliverables
- [ ] Architecture document (complete — see `docs/architecture.md`)
- [ ] Agent catalogue with contracts and boundaries
- [ ] Decision and orchestration workflow diagrams
- [ ] Threshold and escalation notes document
- [ ] Production readiness plan
- [ ] Assumptions and trade-offs document
- [ ] API documentation (OpenAPI spec)
- [ ] Operations runbook

---

## Technical Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| Language | Python 3.12+ | Rich ecosystem for AI/agents, fast prototyping |
| Framework | FastAPI | Async, typed, auto-docs |
| Workflow | Temporal (or custom state machine) | Durable execution, visibility, retry built-in |
| Message Bus | Redis Streams (dev) / Kafka (prod) | Simplicity for prototype, scalability for prod |
| Database | PostgreSQL 16 | ACID, JSONB, partitioning for audit |
| Cache | Redis | Idempotency keys, distributed locks |
| Observability | OpenTelemetry + Prometheus + Grafana | Standard stack |
| Testing | pytest + hypothesis | Property-based testing for decision rules |
| Containers | Docker + Docker Compose | Local dev parity |
| CI/CD | GitHub Actions | Automated testing and linting |

---

## Key Design Decisions

### D1: Temporal vs. Custom State Machine
**Decision**: Start with custom state machine for Phase 1-2, migrate to Temporal for Phase 3-4.
**Rationale**: Reduces initial complexity; Temporal adds significant value for retry, timeout, and visibility but has learning curve.

### D2: Rule-Based vs. ML-Based Decision Engine
**Decision**: Rule-based with configurable thresholds.
**Rationale**: Auditable, deterministic, explainable. ML can be added as a scoring layer later, not as primary decision-maker.

### D3: Sync vs. Async Agent Communication
**Decision**: Async message-passing for all inter-agent communication.
**Rationale**: Decoupling, failure isolation, natural retry semantics, audit trail.

### D4: Single Process vs. Distributed Agents
**Decision**: Single-process in development, distributed in production.
**Rationale**: Faster iteration; agent boundaries are logical (modules), not physical (services) until scaling demands it.

### D5: Real External Integrations vs. Stubs
**Decision**: All external systems stubbed/mocked with realistic behavior.
**Rationale**: Problem statement explicitly excludes production integrations to real rails.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Decision engine produces incorrect action | Duplicate payment / lost funds | Confidence thresholds + human approval for risky actions |
| Agent timeout cascade | Cases stuck indefinitely | SLA timers + automatic escalation on timeout |
| Duplicate event processing | Double-counting exceptions | Idempotency at ingress + egress |
| State corruption from concurrent updates | Inconsistent case state | Optimistic locking + state machine validation |
| Configuration error deploys bad rules | Widespread incorrect decisions | Config validation + gradual rollout + kill switch |

---

## Success Criteria

1. **Functional**: System correctly handles all 7 exception types end-to-end
2. **Performance**: P95 auto-resolution time < 30 seconds for simple cases
3. **Safety**: Zero duplicate payments or incorrect fund movements in testing
4. **Auditability**: Every decision traceable with evidence and justification
5. **Determinism**: Replay any case with same evidence → same decision
6. **Resilience**: System degrades gracefully (escalates to human) on any component failure

---

## Sprint Breakdown (if running 2-week sprints)

| Sprint | Focus | Key Deliverable |
|--------|-------|----------------|
| Sprint 1 | Models, State, Ingress, Basic Orchestration | Single case flows through pipeline |
| Sprint 2 | Investigators, Decision Engine, Egress | Auto-resolution of simple cases |
| Sprint 3 | Async ops, Feedback, Observability | Full loop with retry and replay |
| Sprint 4 | Safety, Config, E2E testing, Documentation | Production-ready deliverable |

---

## Immediate Next Steps

1. Initialize the project with directory structure and dependencies
2. Implement core data models (`ExceptionCase`, `Evidence`, `Decision`)
3. Build the case state machine
4. Implement Ingress Gateway with deduplication
5. Build a single happy-path flow: ingress → orchestrate → investigate (stubbed) → decide → egress

This gets a working skeleton end-to-end in the first sprint, which can then be deepened iteratively.
