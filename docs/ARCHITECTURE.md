# Architecture Decision Record

## Language & framework: Python + FastAPI
- **Why:** fast to iterate, easy to read in a walkthrough, native async for webhook
  ingestion and concurrent provider simulation.
- **Solves:** async I/O-bound workload (many small DB writes, webhook handling).
- **Makes harder:** CPU-bound scale (GIL) — irrelevant here; pacing math is trivial.
  Typed-model ergonomics weaker than Rust/Go — mitigated by small module surface.

## Database: PostgreSQL as the single source of truth
- **Why:** the core problems are *coordination* (two workers, one agent) and *durability*
  (worker crashes mid-call). Postgres gives both with one primitive:
  `SELECT ... FOR UPDATE SKIP LOCKED`, plus transactional state transitions.
- **Solves:** double-allocation, idempotent event application, crash recovery — without
  adding a distributed lock service.
- **Makes harder:** write-path scaling (hot rows). Answered in README §Scaling
  (partition by campaign, shard pacing).

## Why not Kafka / Redis as core infrastructure
- Event volume in this problem is modest; what we need is *exactly-once-ish state
  updates with durability*, which a transactional DB provides directly.
- Kafka would add replay/consumer-group complexity for no benefit at prototype scale;
  Redis as primary store would force us to re-implement durability and atomic
  multi-row allocation. Simpler architecture, same guarantees — and every component
  (stateless workers, DB-coordinated) can later be fronted by a queue if volume demands.

## Worker model: stateless workers coordinated by the DB
- Workers own no state; all truth lives in Postgres. Any worker can process any event;
  crashes lose nothing that was committed. This is what makes the crash scenario a
  watchdog problem instead of a consistency problem.

## Safety boundary: structural, not configurational
- The pacing engine imports nothing from the allocator/providers; it returns an int.
  The Safety Controller is the only code path to `initiate_call`. There is no flag to
  "turn safety off" — removing the controller requires a code change.

## Least confident part / with another week
- Answer-rate estimation is a simple rolling statistic; a real system would want
  per-campaign EWMA with variance-aware confidence (shrink overdial when uncertain).
- Add explicit leases/heartbeats (`worker_id`, `lease_expires_at`) instead of the
  updated_at-based watchdog; DB `LISTEN/NOTIFY` to wake pacing on agent-state changes;
  a `dialer_decisions` table to chart requested vs approved over time.