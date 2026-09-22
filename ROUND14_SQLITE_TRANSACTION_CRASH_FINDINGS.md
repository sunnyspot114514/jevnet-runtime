# Round 14 — SQLite Transaction Crash Boundary

Date: 2026-09-22

This round narrows the durability claim around the SQLite reference backend.

The question is intentionally smaller than physical power-loss correctness:

> What happens if the Python process dies while a SQLite transaction is open,
> versus immediately after COMMIT returns?

Artifact:

sqlite_wal_crash_probe.py

---

## 1. Probe design

The child process opens the same schema used by SQLiteDurableStore:

- journal_mode=WAL
- synchronous=FULL
- append-only durable_records table
- per-record SHA-256

The child begins an IMMEDIATE transaction and attempts either:

- one durable record;
- two durable records.

It is then terminated abruptly:

- before COMMIT;
- or after COMMIT returns.

A fresh process reopens the database through SQLiteDurableStore.

---

## 2. Cases

### One record, crash before COMMIT

Attempted records:

1

Visible after reopen:

0

PRAGMA integrity_check:

ok

### One record, crash after COMMIT

Attempted records:

1

Visible after reopen:

1

PRAGMA integrity_check:

ok

### Two records, crash before COMMIT

Attempted records:

2

Visible after reopen:

0

PRAGMA integrity_check:

ok

### Two records, crash after COMMIT

Attempted records:

2

Visible after reopen:

2

PRAGMA integrity_check:

ok

---

## 3. Reference result

Within this process-crash probe:

- uncommitted batches do not become visible;
- committed batches become fully visible;
- no half-visible two-record batch was observed;
- SQLite integrity_check reports ok after every reopen;
- application-level record checksums continue to validate committed records.

This is the transaction boundary required by the reference DurableStore model.

---

## 4. Application-level corruption detection

SQLiteDurableStore now stores:

payload_json
payload_sha256

Replay recalculates the hash.

A test directly mutates a committed payload without updating its checksum.

Result:

DurableRecordCorruptionError

The runtime therefore stops rather than replaying the modified record as
canonical truth.

Earlier schema versions are migrated by adding and backfilling the checksum
column.

---

## 5. Relationship to Round 13

Round 13 established:

- ambiguous provider outcome -> durable UnresolvedOutcome;
- context/memory projection from durable canonical truth;
- SQLite reopen across independent Python processes;
- separate SQLite runtime/provider/lease stores;
- seven hard-crash cut points.

Round 14 focuses only on the local SQLite transaction boundary underneath those
experiments.

The result strengthens process-crash semantics but does not change the
production-safety claim.

---

## 6. What this does not verify

This probe does not simulate:

- sudden machine power loss;
- torn database pages;
- WAL corruption;
- disk-controller volatile cache loss;
- SSD firmware failure;
- bit rot;
- filesystem journal corruption;
- reordered persistence below SQLite;
- simultaneous loss of runtime/provider/lease storage.

It is therefore inappropriate to describe this as a power-loss proof.

---

## 7. Evidence classification

The project now distinguishes:

### In-memory simulation

Useful for high-volume fault scheduling and invariant exploration.

### Finite model checking

Useful for exhaustive safety results inside an explicit finite abstraction.

### SQLite process-restart tests

Useful for cross-process persistence and replay behavior.

### Abrupt process-kill tests

Useful for execution cut points and transaction-boundary behavior.

### Physical durability

Not yet established.

That final category requires a different experimental setup.

---

## 8. Next durability frontier

A serious next step would use a disposable VM or machine-level fault harness to
interrupt the storage stack below the Python process.

Potential experiments:

1. run SQLite on a disposable filesystem / VM;
2. force host reset during fsync / commit windows;
3. preserve and inspect the resulting WAL/database files after reboot;
4. run integrity_check and application-record checksum validation;
5. compare against expected committed prefixes;
6. repeat under different synchronous/journal modes.

Those experiments should remain separate from the current reference-backend
results.
