# SmartDialer

A working SmartDialer prototype with **progressive** and **predictive** dialing modes,
a hard **Safety Controller** boundary between pacing and the telecom provider,
mock providers with realistic misbehavior (duplicates, out-of-order events, timeouts),
a concurrent-worker-safe allocation layer, tests, a scenario simulator, and a load test.

Stack: **Python 3.10+ / FastAPI / PostgreSQL (asyncpg + SQLAlchemy async)**.

## Architecture

```text
Campaign
   │
   ▼
Pacing Engine (progressive | predictive)      reads live context from DB every tick
   │  "I would like to start N calls"
   ▼
Safety Controller                             may reduce N — including to 0. Never bypassable.
   │  approved M (M <= N)
   ▼
Call Allocator                                reserves borrower (and agent in progressive mode)
   │                                           via SELECT ... FOR UPDATE SKIP LOCKED
   ▼
Telecom Provider A / B (mocks)                async, unreliable by design
   │  webhook events (duplicates, out-of-order, timeouts)
   ▼
FastAPI  POST /webhooks/provider-event        idempotency check + state-transition guard
   │
   ▼
PostgreSQL                                    single source of truth
```

The Dialer Worker runs a tick (default 2s) per active campaign:
release wrap-up agents → reset stale calls (crash watchdog) → build context →
pace → safety-check → allocate/initiate.

## Components

| Path | Responsibility |
|---|---|
| `smartdialer/engine/progressive.py` | 1 available agent → at most 1 agent-bound call |
| `smartdialer/engine/predictive.py` | requests calls from headroom / answer rate, minus ringing adjustment |
| `smartdialer/engine/safety_controller.py` | approve / reduce / reject / fallback-to-progressive; hard abandon-rate stop |
| `smartdialer/allocator/call_allocator.py` | concurrency-safe reservation (`FOR UPDATE SKIP LOCKED`) + provider hand-off |
| `smartdialer/providers/` | provider interface, Provider A (fast/reliable), Provider B (slow/dupes/out-of-order), health registry |
| `smartdialer/workers/dialer_worker.py` | the pacing loop |
| `smartdialer/api/webhooks.py` | normalized provider event ingestion |
| `smartdialer/services.py` | event processing, state-machine guard, context builder, stale-call watchdog |

## Agent state machine

```text
OFFLINE ──> AVAILABLE ⇄ PAUSED
               │ reserve
               ▼
            RESERVED ──> DIALING ──> CONNECTED ──> WRAP_UP ──> AVAILABLE
               │            │
               └── failure ┴──> AVAILABLE   (call failed before connect)
```

**Concurrency rule:** two workers can never reserve the same agent. Reservation is a
single transaction using `SELECT ... FOR UPDATE SKIP LOCKED`; a worker simply cannot
see a row another worker has locked. No application-level locks, no retries needed.
(See `tests/test_agent_allocation.py` and `simulator/load_test.py`: 100 concurrent
workers vs 10 agents → exactly 10 reservations.)

## Call state machine

```text
QUEUED → RESERVED → INITIATED → RINGING → ANSWERED → CONNECTED → COMPLETED
                       │           │          │          │
                       └───────────┴──────────┴────────────> FAILED / CANCELLED
```

Transitions are enforced by an explicit guard table (`states.py`). An event is applied
**only if the call is currently in a valid prior state**; otherwise it is logged and
ignored. Duplicate deliveries are additionally deduplicated by `provider_events.event_id`
(`ON CONFLICT DO NOTHING`). This is what makes "ANSWERED×3 then COMPLETED" and
"COMPLETED before ANSWERED" harmless. (See `tests/test_call_state.py`.)

## Setup

```bash
# 1. PostgreSQL
docker run -d --name smartdialer-postgres \
  -e POSTGRES_USER=smartdialer -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=smartdialer -p 5432:5432 postgres:15

# 2. Environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://smartdialer:password@localhost:5432/smartdialer"
export WEBHOOK_BASE_URL="http://localhost:8000"

# 3. Run (API + dialer worker in one process)
python -m smartdialer.main
```

Tables are created automatically on startup (`init_db`).

## Tests, load test, simulation

```bash
python -m pytest tests/ -v                      # concurrency, state machine, safety controller
python -m smartdialer.simulator.load_test       # 100 concurrent reservations vs 10 agents
python -m smartdialer.simulator.simulation      # scenarios A–D
```

## Simulation results (scenarios A–D)

| Scenario | Answer rate | Requested | Approved | Initiated | Connected | Abandoned |
|---|---|---|---|---|---|---|
| A | 20% | 1073 | 246 | 246 | 46 (~19%) | 0 |
| B | 50% | 265 | 197 | 197 | 97 (~49%) | 0 |
| C | 70% | 90 | 88 | 88 | 62 (~70%) | 0 |
| D | changing | 534 | 228 | 228 | 70 | 0 |

Reading the table:
- The Safety Controller reduced every request (1073 → 246 in A); the pacing engine never touches the provider.
- Observed connect rates track configured answer rates, so the predictive math is calibrated.
- Scenario C requests *fewer* calls: high answer rate + long talk time means little headroom to fill.
- **Abandoned connected calls: 0 in all scenarios** — the safety boundary held, including when conditions changed mid-run (D).

(Full raw output: `simulation_output.txt`.)

## Failure handling

1. **Worker crash** — reservations and call rows are committed before the provider is called; a watchdog (`release_stale_calls`) resets calls stuck in active states past a timeout, releases agents, re-queues borrowers. Events already committed remain consistent; later events still pass the transition guard.
2. **Provider outage** — the registry tracks per-provider success/failure; `choose_provider` prefers the healthy one; above 50% error rate the Safety Controller falls back to progressive limits, above 35% it tightens toward them.
3. **Sudden agent drop** — context is re-read every tick; `available_agents - active_*` headroom collapses, approvals drop to 0 until the gap closes. Reaction time ≈ one tick (2s, configurable).
4. **Duplicate events** — deduplicated by `event_id`; second copy is a no-op.
5. **Out-of-order events** — rejected by the transition guard; the call ends in a sensible state either way.

## Scaling: what breaks first, and the fix

First bottleneck at 10k–100k agents: **PostgreSQL row-lock/index contention on `agents`**
for one campaign (hot pages under `FOR UPDATE SKIP LOCKED`), plus the **single pacing
loop** computing global context. Fixes, in order: partition `agents`/`calls` by
`campaign_id` so workers only lock their own partition; shard campaigns across worker
pools (each pool paces its own campaigns — the design is already stateless-worker +
DB-coordinated, so adding workers is safe); replace per-tick `COUNT(*)` context queries
with maintained counters or short-lived aggregates. "Add more servers" alone doesn't help
because the contention is on shared rows, not CPU.

## Final question

**How do you get predictive utilization with progressive-grade safety?**

Let the pacing engine be optimistic and the Safety Controller be pessimistic, and make
the boundary structural: the pacing engine returns an integer and has no reference to the
provider. The controller converts live state (available agents, active connections,
ringing calls, answer rate, provider health, abandon rate) into a hard cap — expected
new connections may never exceed free agents by more than a small compliance margin —
and degrades smoothly to 1:1 progressive dialing whenever confidence drops (provider
errors, answer-rate volatility, rising abandon rate, sudden agent loss). Predictive
upside when the world is stable; progressive determinism when it isn't. The 3% abandon
rate is a tripwire that stops dialing entirely, not a target to optimize against.

See `docs/ARCHITECTURE.md` for the decision record.