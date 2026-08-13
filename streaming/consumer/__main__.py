"""Betslip consumer: canonicalise, hash, stamp version, batch-insert.

    python -m streaming.consumer --source /tmp/fixture.ndjson
    python -m streaming.consumer --source kafka --brokers localhost:19092 --topic betslips

It does not aggregate, deduplicate or interpret. Supersedence is resolved by the
engine (ADR-0007/0008/0012), and every read collapses with FINAL.

At-least-once delivery and out-of-order arrival are **assumed**, not tolerated:
the same event delivered twice resolves to the same state, and a newer version
wins regardless of when it arrives. Both properties are asserted by the branch's
tests rather than argued for.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "betflow"))

try:
    from src.load import normalise_market, normalise_management_unit  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    # `src.load` imports pandas at module level for the batch path, but the two
    # normalisers are pure `re`/`str`/`unicodedata`. Importing them normally
    # therefore drags the whole analytics stack into a streaming container that
    # otherwise needs nothing but the standard library and a Kafka client —
    # ~50 MB per replica, multiplied by every consumer the scaling demo adds.
    #
    # Loading them from source keeps one authoritative definition (still only in
    # betflow/src/load.py) while letting the consumer run without pandas. A
    # second copy here would be the alternative, and it would drift — which is
    # exactly the failure ADR-0014 records: a rule stated twice diverges.
    #
    # Everything above `read_export` is pure stdlib; every pandas use site is
    # below it. That boundary is asserted rather than trusted, so a future edit
    # moving a pandas call above the split fails loudly here instead of silently
    # importing a broken namespace.
    _path = REPO / "betflow" / "src" / "load.py"
    _prelude, _, _rest = _path.read_text().partition("def read_export")
    if not _rest or "pd." in _prelude:
        raise ImportError(
            f"{_path} no longer splits cleanly at `read_export`: the streaming "
            "consumer relies on the normalisers being pandas-free. Either "
            "install pandas in the consumer image or move them out."
        )
    _ns: dict = {}
    exec(compile(_prelude.replace("import pandas as pd", ""), str(_path), "exec"), _ns)
    normalise_market = _ns["normalise_market"]
    normalise_management_unit = _ns["normalise_management_unit"]

from .canonical import row_key  # noqa: E402
from .insert import Inserter  # noqa: E402

DEFAULT_URL = "http://localhost:18123"


def to_row(event: dict) -> dict:
    """Wire event -> table row. The only place `version` is decided."""
    return {
        "row_key": row_key(event),
        # ADR-0007: version is source snapshot time, and the highest wins. Never
        # arrival time — that would make the winner depend on delivery order,
        # which is the property the contract exists to remove.
        "version": int(event["emitted_at"]),
        "uid": str(event["uid"]),
        "placed_at": event["placed_at"].replace("T", " ").replace("+00:00", ""),
        "event_at": event["event_at"].replace("T", " ").replace("+00:00", ""),
        "bet_type": event["bet_type"],
        "match_id": int(event["match_id"]),
        "fixture": event["fixture"],
        "competition": event["competition"],
        "market": event["market"],
        # Normalised at ingest, not at query time. The feed ships one logical
        # market under several labels — `Saves {PLAYER}`, `{goalnr}{ordinal} goal
        # scorer` — and `normalise_market` collapses them (ADR-0004). Grouping by
        # the raw label instead splits one market into several, which changes
        # which legs share a price-reference group and therefore changes the
        # sharp test's denominator: measured at +5.2% more scoring units.
        #
        # This is canonicalisation, which is the consumer's job — the same
        # argument that puts identity hashing here rather than in SQL.
        "market_normalised": normalise_market(event["market"]),
        "player": event["player"],
        "selection": event["selection"],
        # `RETABET EUSKADI` and `EUSKADI` are one region on different systems,
        # and `CATALUNYA RETA` carries the brand as a suffix. Normalising at
        # ingest keeps one region as one row in every breakdown; leaving it to
        # the reader split ESTATAL from RETABET ESTATAL and inflated the region
        # count from 16 to 24.
        "region": normalise_management_unit(event["region"]),
        "currency": event["currency"],
        "price": event["price"],
        "turnover": event["turnover"],
        "ggr": event["ggr"],
        "net_revenue": event["net_revenue"],
        "event_kind": event["event_kind"],
        "source": event["source"],
        "is_inplay": int(event["is_inplay"]),
        "minutes_to_kickoff": float(event["minutes_to_kickoff"]),
    }


def iter_file(path: str):
    stream = sys.stdin if path == "-" else open(path)
    try:
        for line in stream:
            if line.strip():
                yield json.loads(line)
    finally:
        if stream is not sys.stdin:
            stream.close()


class KafkaSource:
    """Kafka consumer whose offsets advance only behind a completed insert.

    Lag is deliberately NOT computed here. It comes from the broker's
    consumer-group offsets (ADR-0013): a component reporting its own backlog is
    the component under suspicion vouching for itself.

    This is a class rather than a plain generator because the commit point is
    not inside the iteration — it is after the caller's insert returns. A
    generator can yield events but cannot know when the batch they joined was
    durably written, and committing at yield time acknowledges data that is
    still only in a Python list.
    """

    def __init__(self, brokers: str, topic: str, group: str, idle_timeout: float) -> None:
        try:
            from confluent_kafka import Consumer  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "confluent-kafka is not installed. `pip install confluent-kafka`, "
                "or use --source <file> which every consumer test uses."
            ) from exc

        self._topic = topic
        self._idle_timeout = idle_timeout
        self._consumer = Consumer(
            {
                "bootstrap.servers": brokers,
                "group.id": group,
                "auto.offset.reset": "earliest",
                # Offsets commit only after a batch is inserted, so a crash
                # replays the uncommitted batch — safe because ingestion is
                # idempotent (ADR-0007), and tested rather than assumed.
                "enable.auto.commit": False,
                # A partition reassignment must not strand a batch this process
                # already inserted, nor commit one it has not. Both hooks are
                # wired in _on_revoke below.
                "max.poll.interval.ms": 300_000,
                "session.timeout.ms": 45_000,
            }
        )
        self._consumer.subscribe([topic], on_revoke=self._on_revoke)

    def _on_revoke(self, consumer, partitions) -> None:
        """Commit before losing partitions, so a rebalance does not replay work.

        Replaying would be correct — ingestion is idempotent — but it would be
        wasted, and it would make the rescale demo's lag drain look slower than
        the added consumers actually are.
        """
        try:
            consumer.commit(asynchronous=False)
        except Exception:
            # Nothing to commit, or the group already moved on. Not fatal: the
            # uncommitted range simply replays, which is safe by ADR-0007.
            pass

    def __iter__(self):
        """Yield events until the topic goes quiet for `idle_timeout` seconds.

        Yields `None` on an idle poll rather than swallowing it. The caller uses
        that tick to flush a partly-filled batch: without it, a batch smaller
        than `--batch-size` that stops growing is never inserted and never
        committed, because the flush deadline is only ever evaluated on the
        arrival of a *new* event. That is a stall that reads exactly like a
        consumer bug on the lag graph — offsets frozen with the process healthy
        and the group still assigned — and it was one, measured before it was
        fixed.
        """
        last_message = time.monotonic()
        while True:
            message = self._consumer.poll(1.0)
            if message is None:
                if time.monotonic() - last_message > self._idle_timeout:
                    return
                yield None
                continue
            if message.error():
                continue
            last_message = time.monotonic()
            yield json.loads(message.value())

    def commit(self) -> None:
        """Acknowledge everything consumed so far. Called after an insert lands.

        Synchronous on purpose: an async commit can still be in flight when the
        process dies, which would leave the offset ahead of the data in exactly
        the window this ordering exists to close.
        """
        try:
            self._consumer.commit(asynchronous=False)
        except Exception:
            # No offsets to commit yet (nothing consumed since the last one).
            pass

    def close(self) -> None:
        self._consumer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="streaming.consumer")
    parser.add_argument("--source", required=True, help="path to NDJSON, '-' for stdin, or 'kafka'")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--flush-ms", type=int, default=500)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--database", default="srisk")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="betslips")
    parser.add_argument("--group", default="betflow-consumer")
    parser.add_argument("--idle-timeout", type=float, default=10.0)
    parser.add_argument("--stats-interval", type=float, default=5.0)
    args = parser.parse_args(argv)

    inserter = Inserter(url=args.url, database=args.database)
    source = (
        KafkaSource(args.brokers, args.topic, args.group, args.idle_timeout)
        if args.source == "kafka"
        else None
    )
    events = iter(source) if source else iter_file(args.source)

    batch: list[dict] = []
    started = time.monotonic()
    last_flush = started
    next_stats = started + args.stats_interval
    seen = 0

    def flush(now: float) -> None:
        """Insert, then acknowledge — never the other way round.

        The order is the whole contract. Committing first would acknowledge
        events that exist only in this process's memory, and a crash between
        the two would lose them silently. Inserting first means a crash replays
        the uncommitted batch, which ADR-0007's idempotent ingestion makes a
        no-op rather than a duplicate.
        """
        nonlocal last_flush
        if not batch:
            return
        inserter.send(batch)
        batch.clear()
        last_flush = now
        if source:
            source.commit()

    try:
        for event in events:
            # `None` is an idle tick from the Kafka source, not an event: it
            # exists so the flush deadline below is evaluated even when nothing
            # is arriving. The file source never yields it.
            if event is not None:
                batch.append(to_row(event))
                seen += 1

            now = time.monotonic()
            if len(batch) >= args.batch_size or (now - last_flush) * 1000 >= args.flush_ms:
                flush(now)

            if now >= next_stats:
                elapsed = now - started
                print(
                    f"[consumer] {seen:,} events | {seen / elapsed:,.0f} ev/s "
                    f"| {inserter.stats.batches} batches | parts {inserter.part_count()}",
                    file=sys.stderr,
                )
                next_stats = now + args.stats_interval

        flush(time.monotonic())
    except KeyboardInterrupt:
        # A deliberate kill is part of the idempotency test, not an error. The
        # in-flight batch is dropped uncommitted on purpose: restarting replays
        # it from the last committed offset.
        print("[consumer] interrupted; uncommitted batch will replay", file=sys.stderr)
    finally:
        if source:
            source.close()

    elapsed = time.monotonic() - started
    stats = inserter.stats
    print(
        f"[consumer] done: {stats.rows:,} rows in {elapsed:.1f}s "
        f"= {stats.rows / elapsed if elapsed else 0:,.0f} ev/s "
        f"| {stats.batches} batches | {stats.retries} retries "
        f"| parts {inserter.part_count()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
