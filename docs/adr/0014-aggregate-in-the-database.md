# 14. Aggregate in the database; canonicalise at ingest

Date: 2026-08-12

## Status

Accepted. Corrects the refresh design in ADR-0009 and `DESIGN-STREAMING.md`,
both of which specified reusing the batch pipeline's analysis wholesale. The
reuse principle survives for the statistics; it does not survive for aggregation.

## Context

The refresh job read every collapsed row out of ClickHouse into pandas and
aggregated there. The intent was sound and is recorded in
`streaming/refresh/source.py`: the sharp test's validation against a null
(ADR-0006, 0 flags in 20 of 20 random runs) is worth more than a round trip, and
reusing validated code makes an oracle comparison meaningful.

Applied to *every* metric, it was wrong. Measured at 20M rows:

| | Cost |
|---|---|
| Transfer + parse rows into pandas, before aggregating | **~11 s** |
| Aggregate the same 20M rows in ClickHouse | **2.73 s** |

That is ClickHouse used as a storage engine with the analysis still in Python —
which is what made the batch pipeline slow in the first place. The exercise asks
how millions of events per minute reach a front end quickly; answering it with
"a better database, and the same aggregation in pandas" moves the bottleneck
without removing it.

The concurrent-load measurement made it concrete. Under sustained 500k/min
ingest, refresh ticks ran **2.12 s to 13.76 s** as the table grew from 76k to
577k rows. Read latency held at 1.71 ms throughout — the artifact boundary
guarantees that — but freshness degraded from 5 s to 14 s, and would keep
degrading.

## Decision

**Class 1 aggregates in SQL. Classes 2 and 3 stay in pandas, over data the
database has already reduced.**

| Work | Where | Why |
|---|---|---|
| Breakdowns, counts, money by currency, daily series, timing phases | **ClickHouse** | Pure aggregation — what the engine exists for |
| Price reference, Gini/Lorenz | pandas, over reduced input | Window functions and whole-population sorts, on tens of thousands of rows |
| Wilson bound, exact binomial, Benjamini–Hochberg | pandas, over ~700 rows | Validated against a null (ADR-0006); reimplementing in SQL discards that evidence |

The division is by **what the operation is**, not by convenience: additive
aggregation over many rows belongs in the engine; whole-set statistics over few
rows belong where they are already tested.

**Measured after wiring, on 76,603 rows:**

```
             pandas    SQL
read          0.39s    0.029s
analysis      1.36s    0.56s
total         1.76s    0.59s      3x
```

The gap widens with volume, because the SQL path returns tens of rows regardless
of table size while the pandas path transfers all of them.

### Canonicalisation belongs at ingest

This is the load-bearing half of the record, and it was learned the hard way.

Moving aggregation into SQL surfaced four divergences against the pandas oracle.
Every one had the same cause: **a derived field the batch pipeline computed on
read, which the SQL path had no way to reproduce.**

| Field | What was wrong | Measured effect |
|---|---|---|
| `is_inplay` | Export adapter wrote `0` for every row | 5,539 in-play legs treated as pre-match, inflating the sharp test's scoring units by **5.2%** |
| `market_normalised` | Not stored | Price-reference groups key off it (ADR-0004); the raw label splits one market into several |
| `region` | Not normalised | `ESTATAL` and `RETABET ESTATAL` counted separately — 24 values where the pipeline sees 16 |
| Betslip identity | `GROUP BY uid, placed_at, bet_type` | A customer placing several SIMPLE bets in one second has several betslips (ADR-0003): 1,662 such groups, 3,265 betslips, a **5.9% undercount** propagating into every betslip-grain figure including turnover |

**So: every field the analysis depends on is computed once, at ingest, and
stored.** The consumer already owned canonicalisation for the identity hash;
this extends the same rule to every derived field. A field left for the reader to
derive is a field that will be derived differently by two readers.

After the four corrections, the SQL path matches the pandas path exactly:

```
by_competition        16/16 rows exact
by_market_normalised  16/16 rows exact
by_player             16/16 rows exact
by_region (betslip)   16/16 rows exact, 55,299 = 55,299
sharp reduction       7,606/7,619 windows exact (99.8%)
```

The residual 13 windows are the 155 legs whose timestamps tie at their group's
final observation. The batch pipeline resolves those ties by **spreadsheet row
order** — `cumcount` after a sort — which a stream does not have and ADR-0007
deliberately makes irrelevant. The SQL treats simultaneous legs as simultaneous,
which is the more defensible rule, and the difference is recorded rather than
engineered away.

## Consequences

**Positive**

- The exercise's central question has an answer that survives scrutiny: the
  aggregation runs where the data is, and the front end reads a precomputed
  artifact at 1.71 ms regardless of table size.
- Class 1 tick is 0.59 s against a 1–5 s cadence — 8x headroom, where the pandas
  path had 3x and would have exhausted it at 20M.
- Classes 2 and 3 read rows only when requested, so a class-1 tick pays nothing
  for them.
- The four canonicalisation bugs were latent in the pandas path too. The SQL
  migration is what surfaced them.

**Negative**

- **The batch pipeline's rules are now restated in two places**, and they can
  drift. Ranking by count, money nested per currency, the `__other__` rollup and
  the betslip identity all exist in SQL and in Python. The oracle comparison is
  the only thing keeping them honest, and it must stay in the test path rather
  than becoming a one-off.
- Four ClickHouse traps cost real time and are documented in the code because
  they will recur: `FINAL AS alias` is a syntax error; aliasing an aggregate to a
  GROUP BY column's name is rejected (hit three separate times);
  `argMin(x, x)` is a 500; and reading TSV turns an empty string into NaN, which
  rendered an unresolved currency as a currency literally named `nan` holding
  28,831.69 in real money.
- **ClickHouse accepts unknown columns in `JSONEachRow` and returns HTTP 200.**
  A typo in a column name loses data with no error at all. This is a standing
  hazard for the ingest path, not a one-off.
- Storing derived fields means a change to a derivation rule requires
  reprocessing, where the pandas path would have picked it up on the next read.
  That is the price of the divergences above not existing.
- Timing here is from a machine also running a concurrent Kafka workstream. The
  ratio is sound; absolute figures are not a production sizing.
