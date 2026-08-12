> Part of the [build plan](../BUILD-PLAN.md). Conventions (`$CH`, `$FP`) are
> defined there. Update this file with what was actually measured once the
> branch lands — the plan is corrected by results, not defended against them.

## Branch 5: `feat/load-harness`

**Scope.** The live demo, scripted so it is reproducible: step the rate
through the DESIGN-STREAMING schedule, sample the operations feed throughout,
write one JSON record per run. The dashboard is the demonstration; the JSON is
the evidence.

**Files.**

```
streaming/load/harness.py          # rate schedule, sampling, record writing
streaming/load/results/            # one JSON per run (committed)
```

**The run:**

```bash
python -m streaming.load.harness \
  --plan baseline:70000:120,ceiling:500000:300,past:1000000:300,hold:1000000:180 \
  --record streaming/load/results/run-$(date +%s).json
# Record fields: per step — target rate, achieved rate, lag series (events and
# seconds), refresh p50/p99 per class, part count, artifact hashes, and a
# varnishstat snapshot if branch 4 landed.
```

Then the live part, settled by ADR-0013: `docker compose up -d --scale
consumer=3` mid-hold, Kafka rebalances the partitions, and the record shows lag
draining without a restart. Lag is read from the broker's consumer-group
offsets rather than self-reported by the consumer, which is the reason the log
is there at all. The step past the brief's ceiling is the point: find where it degrades
on this machine, name the saturated component from the panel (expected: CPU
contention inside the 4-CPU allocation or the ClickHouse insert path — both
are expectations, not measurements, and the first prediction in this project
was two orders of magnitude off), and remove it live. Scaling consumers
mid-flight is only safe because ingestion is idempotent — branch 2's tests are
what make step 5 of the demo honest (ADR-0007).

**Done when** the record exists with every field populated, the ceiling on
this machine is a measured number with a named cause, and — where degradation
was reached — the drain after scaling is in the lag series.

**Sequencing note.** A reduced harness (rate schedule + lag/refresh sampling,
no Varnish figures, panel optional) only needs branches 1–3. If branch 4 is at
risk, the harness runs against the refresh job's own metrics rather than
waiting — measurement never waits on presentation.

---

---

## Risk

**Harness — nothing degrades.** With 32–108x per-event headroom, even 1M/min
may not produce visible lag, leaving the demo without its third act. Fallback:
keep raising the dial (the producer is not the bottleneck) until Docker's CPU
budget binds — the ceiling exists, it is just higher than the brief; a
measured "this machine saturates at X" is a stronger answer than a staged
failure. Inverse risk: ClickHouse degrades non-recoverably under the burst
(part explosion, delayed merges) and the drain never comes. Fallback: the
record keeps the degradation series — a measured failure mode with a named
cause is presentable; an unmeasured success is not.
