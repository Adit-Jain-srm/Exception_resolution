const API = '';

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab).classList.add('active');
    });
});

// Agent persona data
const AGENT_PERSONAS = [
    { name: 'Ingress Guardian', role: 'Gatekeeper & Normalizer', model: null, traits: ['Meticulous', 'Skeptical', 'Protective'], desc: 'Assumes all incoming data is potentially malformed. Rejects aggressively - false rejection is safer than bad data flowing through. Never passes data it hasn\'t validated.' },
    { name: 'The Conductor', role: 'Workflow Director', model: 'GPT-4o-mini', traits: ['Calm', 'Decisive', 'Time-aware'], desc: 'Constantly aware of SLA timers. Parallelizes aggressively but consolidates carefully. Escalates early rather than risking breach. Treats timeout as a decision, not an error.' },
    { name: 'The Detectives', role: 'Evidence Gatherers (x7)', model: null, traits: ['Thorough', 'Factual', 'Non-judgmental'], desc: 'Reports ONLY what they find - never interprets. Clearly distinguishes fact from inference. Returns INCONCLUSIVE when ambiguous. Operates under strict time budget.' },
    { name: 'The Judge', role: 'Decision Engine', model: 'GPT-4o', traits: ['Analytical', 'Conservative', 'Principled'], desc: 'Weighs evidence by confidence. Errs on caution - when uncertain, HOLD or ESCALATE. Generates explicit justification for audit. Same evidence always yields same decision.' },
    { name: 'Safety Gate', role: 'Guardrail Pipeline', model: null, traits: ['Strict', 'Vigilant', 'Unyielding'], desc: 'Validates every decision against allowlist, confidence floor, amount threshold, and hallucination markers. Can override LLM decisions when safety is at risk.' },
    { name: 'The Operator', role: 'Action Executor', model: null, traits: ['Methodical', 'Double-checking', 'Cautious'], desc: 'Verifies pre-conditions before EVERY action. Uses idempotency keys on every call. On any ambiguity or failure, defaults to HOLD. Check twice, execute once.' },
    { name: 'The Follow-Up', role: 'Async Coordinator', model: 'GPT-4o-mini', traits: ['Reliable', 'Persistent', 'Non-blocking'], desc: 'Never blocks the primary path. Handles notifications, retry scheduling, and SLA timers. Accepts eventual consistency - delivery over speed.' },
    { name: 'The Historian', role: 'Feedback Analyzer', model: 'GPT-4o', traits: ['Reflective', 'Pattern-seeking', 'Thorough'], desc: 'Correlates new events to historical cases. Identifies when new evidence contradicts prior decisions. Tracks outcome patterns for rule refinement.' },
];

function renderAgents() {
    const grid = document.getElementById('agents-grid');
    grid.innerHTML = AGENT_PERSONAS.map(a => `
        <div class="agent-card">
            <div class="agent-card-header">
                <span class="agent-name">${a.name}</span>
                ${a.model ? `<span class="agent-model-badge">${a.model}</span>` : '<span class="agent-model-badge" style="background:rgba(34,197,94,0.1);color:#22c55e;border-color:rgba(34,197,94,0.3)">No LLM</span>'}
            </div>
            <div class="agent-role">${a.role}</div>
            <div class="agent-desc">${a.desc}</div>
            <div class="agent-traits">${a.traits.map(t => `<span class="trait-tag">${t}</span>`).join('')}</div>
        </div>
    `).join('');
}

function getActionClass(status) {
    if (!status) return '';
    if (status === 'RESOLVED') return 'action-resolved';
    if (status === 'ESCALATED') return 'action-escalated';
    if (status === 'HELD') return 'action-held';
    return '';
}

function renderCaseCard(result, index) {
    if (!result || result.status === 'DEDUPLICATED') return '';
    const decision = result.decision || {};
    return `
        <div class="case-card" style="animation-delay: ${index * 0.08}s">
            <div class="case-card-header">
                <span class="case-type type-${result.exception_type}">${result.exception_type.replace(/_/g, ' ')}</span>
                <span class="case-amount">${result.currency} ${Number(result.amount).toLocaleString()}</span>
            </div>
            <div class="case-card-body">
                <div class="payment-id">${result.payment_id} | ${result.payment_rail}</div>
                <div class="justification">${decision.justification ? decision.justification.slice(0, 150) + '...' : 'Processing...'}</div>
            </div>
            <div class="case-card-footer">
                <span class="action-badge ${getActionClass(result.final_status)}">${result.action_taken || 'PENDING'}</span>
                <span class="case-meta">${result.elapsed_ms}ms | ${result.evidence?.length || 0} evidence | ${decision.confidence || '?'} conf</span>
            </div>
        </div>
    `;
}

// DEMO
let demoResults = [];

document.getElementById('run-all-btn').addEventListener('click', async () => {
    const btn = document.getElementById('run-all-btn');
    btn.disabled = true;
    btn.textContent = 'Processing...';
    document.getElementById('cases-grid').innerHTML = '<p style="color:var(--text-muted);padding:20px;">Running all exceptions through the pipeline...</p>';

    try {
        const res = await fetch(`${API}/api/process-all`, { method: 'POST' });
        const data = await res.json();
        demoResults = data.results;

        document.getElementById('cases-grid').innerHTML = demoResults.map((r, i) => renderCaseCard(r, i)).join('');

        const stats = data.stats;
        document.getElementById('demo-stats').innerHTML = `
            <strong>${data.successful}/${data.total}</strong> resolved |
            <strong>${stats.ingress.duplicates}</strong> deduped |
            <strong>${stats.guardrail_violations}</strong> guardrail overrides
        `;

        renderTraceSelector(demoResults);
    } catch (err) {
        document.getElementById('cases-grid').innerHTML = `<p style="color:var(--danger);padding:20px;">Error: ${err.message}. Make sure the server is running (uvicorn src.server:app)</p>`;
    }

    btn.disabled = false;
    btn.textContent = 'Process All Exceptions';
});

document.getElementById('reset-btn').addEventListener('click', () => {
    document.getElementById('cases-grid').innerHTML = '';
    document.getElementById('demo-stats').innerHTML = '';
    demoResults = [];
    document.getElementById('trace-selector').innerHTML = '';
    document.getElementById('trace-detail').innerHTML = '';
});

// TRACES
function renderTraceSelector(results) {
    const selector = document.getElementById('trace-selector');
    selector.innerHTML = results.filter(r => r && r.status !== 'DEDUPLICATED').map((r, i) => `
        <button class="trace-btn" data-index="${i}">${r.exception_type.replace(/_/g, ' ')}<br><small>${r.payment_id}</small></button>
    `).join('');

    selector.querySelectorAll('.trace-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            selector.querySelectorAll('.trace-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTrace(results[parseInt(btn.dataset.index)]);
        });
    });
}

function renderTrace(result) {
    if (!result) return;
    const detail = document.getElementById('trace-detail');

    const steps = result.steps || [];
    const evidence = result.evidence || [];
    const decision = result.decision || {};

    let html = `
        <div style="margin-bottom:20px;">
            <h3 style="font-size:16px;margin-bottom:4px;">${result.payment_id} - ${result.exception_type.replace(/_/g, ' ')}</h3>
            <p style="font-size:13px;color:var(--text-muted);">${result.currency} ${Number(result.amount).toLocaleString()} | ${result.payment_rail} | Priority: ${result.priority}</p>
        </div>
        <div class="trace-timeline">
    `;

    steps.forEach((step, i) => {
        let cls = 'trace-step';
        if (step.includes('ERROR') || step.includes('GUARDRAIL')) cls += ' step-error';
        else if (step.includes('DECISION') || step.includes('EGRESS')) cls += ' step-success';
        else if (step.includes('INVESTIGATION')) cls += ' step-warning';

        html += `
            <div class="${cls}">
                <div class="trace-step-content">
                    <div class="trace-step-label">Step ${i + 1}</div>
                    <div class="trace-step-detail">${step}</div>
                </div>
            </div>
        `;
    });

    html += '</div>';

    if (evidence.length > 0) {
        html += `<div style="margin-top:24px;"><h4 style="font-size:14px;color:var(--accent-glow);margin-bottom:12px;">Evidence Bundle (${evidence.length} items)</h4>`;
        html += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;">`;
        evidence.forEach(e => {
            const confColor = e.confidence === 'HIGH' ? 'var(--success)' : e.confidence === 'MEDIUM' ? 'var(--warning)' : 'var(--danger)';
            html += `<div style="padding:10px;background:var(--bg-elevated);border-radius:6px;font-size:12px;">
                <div style="font-weight:600;margin-bottom:4px;">${e.source}</div>
                <div style="color:var(--text-muted);">${e.type}</div>
                <div style="color:${confColor};font-weight:500;margin-top:4px;">Confidence: ${e.confidence}</div>
            </div>`;
        });
        html += '</div></div>';
    }

    if (decision.justification) {
        html += `<div style="margin-top:24px;padding:16px;background:var(--bg-elevated);border-radius:8px;border-left:3px solid var(--accent);">
            <h4 style="font-size:14px;color:var(--accent-glow);margin-bottom:8px;">Decision: ${decision.action}</h4>
            <p style="font-size:13px;color:var(--text-secondary);line-height:1.6;">${decision.justification}</p>
            <div style="margin-top:8px;font-size:11px;color:var(--text-muted);">
                Confidence: <strong>${decision.confidence}</strong> | Risk: <strong>${decision.risk_level}</strong> | Approval required: <strong>${decision.requires_approval}</strong>
            </div>
            <div style="margin-top:6px;font-size:11px;color:var(--text-muted);">Rules: ${decision.rules_applied?.join(', ') || 'N/A'}</div>
        </div>`;
    }

    detail.innerHTML = html;
}

// Init
renderAgents();
