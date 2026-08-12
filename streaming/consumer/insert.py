"""Batched inserts into ClickHouse over the HTTP interface.

Standard library only: no ClickHouse client is installed on the target machine
and this needs none — `INSERT ... FORMAT JSONEachRow` over HTTP is a POST with a
newline-delimited body.

**Append only, never UPDATE.** Supersedence is the engine's job via
ReplacingMergeTree(version) (ADR-0007, ADR-0008). A consumer that tried to update
in place would be both slower and wrong: ClickHouse mutations rewrite whole parts.

Batch size is a correctness-adjacent knob, not just a throughput one. Every
insert creates a part, and `FINAL` over 5 parts costs 2.8x what it costs over one
(ADR-0012) — so an over-eager flush degrades the *read* path while the write path
looks healthy. That coupling is easy to misattribute, which is why part count is
reported alongside throughput.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

INSERT_SQL = "INSERT INTO srisk.betslip_leg FORMAT JSONEachRow"

# Columns in schema order. Anything the source does not carry is derived here or
# defaulted — the table has no nullable columns by design.
COLUMNS = (
    "row_key",
    "version",
    "uid",
    "placed_at",
    "event_at",
    "bet_type",
    "match_id",
    "fixture",
    "competition",
    "market",
    "player",
    "selection",
    "region",
    "currency",
    "price",
    "turnover",
    "ggr",
    "net_revenue",
    "event_kind",
    "source",
    "is_inplay",
    "minutes_to_kickoff",
)


@dataclass
class Stats:
    rows: int = 0
    batches: int = 0
    retries: int = 0
    seconds: float = 0.0

    @property
    def rate(self) -> float:
        return self.rows / self.seconds if self.seconds else 0.0


@dataclass
class Inserter:
    url: str
    user: str = "srisk"
    password: str = "srisk"
    database: str = "srisk"
    max_retries: int = 3
    stats: Stats = field(default_factory=Stats)

    def _endpoint(self) -> str:
        query = urllib.parse.urlencode(
            {
                "user": self.user,
                "password": self.password,
                "database": self.database,
                "query": INSERT_SQL,
                # Let the server accept a batch whose rows arrive slightly out of
                # order relative to the sort key; ordering is the merge's job.
                "input_format_import_nested_json": 1,
            }
        )
        return f"{self.url}/?{query}"

    def send(self, rows: list[dict]) -> None:
        if not rows:
            return
        body = "\n".join(json.dumps(r, separators=(",", ":")) for r in rows).encode()
        started = time.monotonic()

        for attempt in range(self.max_retries):
            try:
                request = urllib.request.Request(self._endpoint(), data=body, method="POST")
                with urllib.request.urlopen(request, timeout=60) as response:
                    response.read()
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                self.stats.retries += 1
                if attempt == self.max_retries - 1:
                    raise SystemExit(f"insert failed after {self.max_retries} attempts: {exc}")
                # Retrying an insert is safe precisely because ingestion is
                # idempotent (ADR-0007): a batch that landed before the timeout
                # resolves to the same state when sent again.
                time.sleep(0.5 * (attempt + 1))

        self.stats.rows += len(rows)
        self.stats.batches += 1
        self.stats.seconds += time.monotonic() - started

    def part_count(self) -> int:
        """Active parts — the number that governs read-side `FINAL` cost."""
        query = urllib.parse.urlencode(
            {
                "user": self.user,
                "password": self.password,
                "database": self.database,
                "query": (
                    "SELECT count() FROM system.parts "
                    "WHERE database='srisk' AND table='betslip_leg' AND active"
                ),
            }
        )
        try:
            with urllib.request.urlopen(f"{self.url}/?{query}", timeout=10) as response:
                return int(response.read().decode().strip())
        except Exception:
            return -1
