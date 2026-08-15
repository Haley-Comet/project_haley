# Comet Order Status & Query Doctrine

*Taught 2026-08-15 from facts verified live against the database that day. Source: Haley-approved handoff of 2026-08-12.*

## Order status codes & lifecycle

Sequence `N -> C -> R -> S -> P`.

- `N` = New/Active - dispatched, in-flight, not yet delivered. **"Active orders" means `status = 'N'`.**
- `C` = Completed - delivery done, awaiting rating. Brief (<= ~1 day normally).
- `R` = Rated - delivered + priced.
- `S` = Statemented - invoiced/finalized.
- `P` = Paid - settled (terminal).
- `D` = Deleted/Cancelled - removed from the table (`cancelled_at` column exists but is unused).

## Query rules (authoritative)

- **Active orders = `WHERE status = 'N'`** - a *positive* select. **Never** define "active" by exclusion (`status <> 'C'` or similar): the table holds **92,710 legacy rows whose status is the literal string `'created'`** (pre-Apr-2026 bulk import), and any exclusion pattern sweeps them in and inflates counts. `status = 'N'` excludes both the legacy block and everything downstream automatically.
- "Open/unrated" (if ever needed) = `status IN ('N','C')`.
- `"Orders"` (capital, double-quoted) is a **VIEW** over a lowercase `orders` base table. There is **no PK/unique index**; `ordertrackingid` is the de-facto unique key (re-verified 2026-08-15: 99,348 rows, all distinct).
- Account rollups are **lifetime** and include the legacy `'created'` block (Haley's decision, Aug 12 2026).
- Row counts other than the frozen legacy block (92,710) drift daily - never quote a cached count; query for it.
