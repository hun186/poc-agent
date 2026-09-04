# Requirement scheduling control plane (Phase 1C-A)

Phase 1C-A provides the `sra_schedule` SQL Server control plane, structured `daily`, `weekly`, `monthly`, and elapsed-duration `interval` recurrence, and `coalesce_latest` for downtime while a schedule remains enabled. Disable is an intentional pause and clears `next_run_at`; re-enable starts strictly after server transaction UTC.

Set `REQUIREMENT_SCHEDULER_ENABLED=true`, `REQUIREMENT_CONTROL_DB_CONNECTION`, `REQUIREMENT_SCHEDULE_DB_SCHEMA` (default `sra_schedule`), `REQUIREMENT_DB_SCHEMA` (default `sra_requirement`), and the existing named SQL registry. Startup transactionally initializes/validates schema v1 and fails closed. The SQL principal needs read/reference access to Phase 1B and DDL/DML only in Phase 1C.

Authenticated readers may inspect schedules. `db_operator` creates disabled schedules, renames disabled metadata, and creates immutable draft versions. `superuser` approves/activates versions and enables/disables automation. Authorization denial uses the canonical audit path.

Gate A has no recurring worker, manual trigger execution, Phase 1A bridge, Report Job/Agent/Elasticsearch execution, or Word serving. Do not run or document `python -m requirement_scheduler worker`; that belongs to Phase 1C-B and cannot begin until Gate A is merged and implementation review passes. Phase 1C live SQL Server acceptance is **NOT EXECUTED** without explicit authorization.
