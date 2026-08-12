# 12. Collapse with FINAL, not argMax — and measure before recommending

Date: 2026-08-12

## Status

Accepted. **Supersedes the read-path mechanism of ADR-0008**, which recommended
the opposite on reasoning that measurement contradicts. ADR-0008's choice of
ClickHouse, its engine, and its schema stand; only the collapse idiom and the
performance claims are replaced.

## Context

ADR-0008 specified how reads resolve ADR-0007's supersedence:

> **Reads collapse explicitly with `argMax(col, version) GROUP BY row_key`, not
> with `FINAL`.** `FINAL` forces the merge at query time and is the wrong default
> under a 100-reader refresh loop.

That was written from plausible reasoning and **was merged without being run**.
It is wrong in both halves.

### What was measured

20M synthesised rows with the shape of the real export (Gini 0.820 against a
measured 0.803, median 4 legs per Uid against 4, cardinalities matched exactly),
plus 2M superseding rows carrying a higher version — 22M rows over 20M distinct
identities. ClickHouse 24.8 in Docker, limited to 2 CPUs and 4 GB.

**The correctness case first, because it is the reason any of this matters.**

```sql
-- No collapse: counts superseded versions as if they were separate legs
SELECT round(sum(ggr), 2) AS ggr, count() AS legs FROM srisk.betslip_leg;

-- Collapsed
SELECT round(sum(ggr), 2) AS ggr, count() AS legs FROM srisk.betslip_leg FINAL;
```

| | GGR | Rows |
|---|---|---|
| No collapse | **+25,164,550.81** | 22,000,000 |
| `FINAL` | **-43,599,923.32** | 20,000,000 |

**The sign inverts.** Uncollapsed, the book appears to have made 25.1M; it
actually lost 43.6M. ADR-0008 predicted this failure ("silently wrong, in the
direction of double-counting revenue") but understated it: the error is not an
inflation, it can reverse the answer.

**The magnitude is not a constant and must not be quoted as one.** An earlier run
of this same comparison produced a 22% overstatement rather than a sign
inversion. Both are correct measurements of different reversal waves — the error
depends on *which* facts were revised and by how much, so it is a property of the
correction pattern, not of the architecture. The defensible claim is the
mechanism, not a percentage.

A single identity shows it without aggregation:

```sql
SELECT version, event_kind, ggr, turnover
FROM srisk.betslip_leg
WHERE row_key = 316712281023910527
ORDER BY version;
```

| version | event_kind | ggr | turnover |
|---|---|---|---|
| 1755000019442 | `placement` | **-236,071.37** | 110,005.30 |
| 1755001019442 | `reversal` | **+110,005.30** | 110,005.30 |

The customer won, the house paid out 236,071 — then the bet was voided and the
house kept the 110,005 stake. Note `ggr == turnover` on the reversal: the same
signature measured in the real export, where 14 of 14 revised rows showed
exactly that. Summing both rows gives -126,066; the truth is +110,005.

**A further property, and the reason this is worse than a consistent error.**
ClickHouse's background merge eventually collapses these rows on its own. Once it
has, the uncollapsed query starts returning the right answer. The same query
against the same table is therefore wrong or right depending on whether a merge
has run — an intermittent fault that will not reproduce in a test and will appear
in production under ingest pressure, which is precisely when it is least
welcome.

**The mechanism comparison, which is where ADR-0008 was wrong.**

```sql
-- A: the idiom ADR-0008 recommended
SELECT market, currency, count(), sum(turnover)
FROM (
    SELECT row_key,
           argMax(market, version)   AS market,
           argMax(currency, version) AS currency,
           argMax(turnover, version) AS turnover
    FROM srisk.betslip_leg GROUP BY row_key
)
GROUP BY market, currency;

-- B: the idiom ADR-0008 advised against
SELECT market, currency, count(), sum(turnover), sum(ggr)
FROM srisk.betslip_leg FINAL
GROUP BY market, currency;
```

| Idiom | Result |
|---|---|
| `argMax` per `row_key` (A) | **MEMORY_LIMIT_EXCEEDED at 3.6 GiB, after 52s** |
| `FINAL` (B) | **0.29–0.82s depending on part layout** |

The recommended idiom does not merely underperform — it **cannot complete** at
target volume on this hardware.

### Why the reasoning failed

`GROUP BY row_key` builds a hash table keyed by 20M distinct identities, holding
every projected column, before any aggregation happens. Memory grows with the
number of identities, which at target volume exceeds the budget.

`FINAL` does not "force a merge" in the sense assumed. Parts are already sorted
by the `ORDER BY` key, so it performs a **streaming merge** over sorted runs:
memory is bounded, cost is close to linear in rows read. It is the operation the
engine is built around.

The error was assuming an unfamiliar keyword must be expensive, and that an
explicit formulation must therefore be cheaper. The cost model was never checked.

### What the timing actually depends on

Two factors dominate, and both are configuration rather than engine limits.

**Part count.** With 5 active parts, `FINAL` merges across them at query time.

```sql
OPTIMIZE TABLE srisk.betslip_leg FINAL;   -- 28.3s, 22M rows -> 20M in one part
```

| State | Single breakdown with `FINAL` |
|---|---|
| 5 parts, 2M uncollapsed duplicates | **0.82s** |
| 1 part, physically deduplicated | **0.29s** |

**Thread count**, measured post-`OPTIMIZE`:

| `max_threads` | Time |
|---|---|
| 1 | 1.384s |
| 2 | **0.319s** |
| 4 | 0.320s |
| 8 | 0.402s |

Saturation at 2 is the container's CPU limit, not the engine's ceiling. The
regression at 8 is scheduling overhead on 2 available cores.

**Seven breakdowns**, the dashboard's actual read load: **6.06s** when run as
seven separate table scans, **0.93s** as a single-pass aggregate. The dashboard
should therefore issue one pass, not seven — a design consequence that only
became visible by measuring.

### A cost ADR-0008 did not anticipate

Storage is **1.16 GiB for 20M rows (62 bytes/row)** at a compression ratio of
only **1.5x** — well below the ~10x a columnar store usually delivers, and above
the 0.3–0.8 GB ADR-0008 estimated.

```sql
SELECT column,
       formatReadableSize(sum(column_data_compressed_bytes))   AS compressed,
       round(sum(column_data_uncompressed_bytes)
             / greatest(sum(column_data_compressed_bytes), 1), 1) AS ratio
FROM system.parts_columns
WHERE database = 'srisk' AND active
GROUP BY column ORDER BY sum(column_data_compressed_bytes) DESC;
```

| Column | Compressed | Ratio |
|---|---|---|
| `row_key` | 153 MiB | **1.0x** |
| `event_at` | 114 MiB | 1.3x |
| `placed_at` | 114 MiB | 1.3x |
| `uid` | 107 MiB | 1.1x |
| `minutes_to_kickoff` | 77 MiB | **1.0x** |

The `LowCardinality` dimensions ADR-0008 emphasised compress well and are *not*
the footprint. The cost sits in the high-entropy columns, and its cause is
`ORDER BY row_key`: ordering by a hash scatters every other column randomly, so
delta and LZ4 encoding have no locality to exploit. The sort key that supersedence
requires is the same one that defeats compression.

Tested: `ORDER BY (placed_at, row_key)` gives 1.06 GiB and 0.385s against 1.16
GiB and 0.513s — a 9% storage gain, not a fix. The entropy is in `row_key` and
`uid` themselves.

## Decision

**Reads collapse with `FINAL`.** The `argMax` formulation is rejected on measured
grounds: it exceeds memory at target volume.

**The `betslip_leg_current` view is rewritten to use `FINAL`**, so the collapse
stays encapsulated and no caller can forget it — the intent of ADR-0008's view,
with a mechanism that works.

**The refresh job issues one single-pass aggregate**, not seven scans: 0.93s
versus 6.06s for the same result.

**`OPTIMIZE TABLE … FINAL` on sealed partitions is promoted from a scaling
contingency (ADR-0010) to routine operation.** It is worth 2.8x on read latency,
and its cost (28.3s for 20M rows) is paid off the read path.

**Process: a mechanism recommendation does not enter an ADR without being run.**
This record exists because ADR-0008 named a specific idiom, advised against
another, and was merged on reasoning alone. In a project whose central claim is
that every figure carries its evidence, an unmeasured technical recommendation is
a contradiction. Reasoning may justify a decision; it may not stand in for
measuring one when measuring is possible.

## Consequences

**Positive**

- The number the exercise turns on now exists: **0.29s to aggregate 20M rows with
  a correct collapse**, against 8.4s for the batch pipeline over 113k rows. Three
  orders of magnitude more data, an order of magnitude less time.
- The sign-inverting GGR error makes ADR-0007's mutability finding concrete, and
  reproducible down to a single identity: it is what happens if the collapse is
  skipped.
- Every claim here is reproducible from the queries above against the schema in
  `streaming/schema/`.
- The single-pass finding changes the refresh design before it is built.

**Negative**

- Storage is ~1.5x larger than estimated, and the cause is structural. The
  identity key is a hash by necessity, and a hash sort key forfeits most columnar
  compression. Accepted, not solved.
- `FINAL` on many small parts is materially slower, so read latency now depends on
  merge state — an operational property, not just a query property. The refresh
  job must be resilient to a slow read after a heavy ingest burst.
- Measurements come from a 2-CPU container. They establish feasibility and the
  shape of the curve; they are not a production sizing.
- One prediction in this record remains untested: that the collapse cost grows
  until it dominates at ~2B rows (ADR-0010). Recorded as prediction, and marked
  as such.
