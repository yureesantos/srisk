"""Betslip consumer: canonicalise, hash, stamp version, batch-insert.

    python -m streaming.consumer --source /tmp/fixture.ndjson
    python -m streaming.consumer --source kafka --topic betslips

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

from .canonical import row_key
from .insert import Inserter

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
        "player": event["player"],
        "selection": event["selection"],
        "region": event["region"],
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


def iter_kafka(brokers: str, topic: str, group: str, idle_timeout: float):
    """Consume until the topic goes quiet for `idle_timeout` seconds.

    Lag is deliberately NOT computed here. It comes from the broker's
    consumer-group offsets (ADR-0013): a component reporting its own backlog is
    the component under suspicion vouching for itself.
    """
    try:
        from confluent_kafka import Consumer  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "confluent-kafka is not installed. `pip install confluent-kafka`, "
            "or use --source <file> which every consumer test uses."
        ) from exc

    consumer = Consumer(
        {
            "bootstrap.servers": brokers,
            "group.id": group,
            "auto.offset.reset": "earliest",
            # Offsets commit only after a batch is inserted, so a crash replays
            # the uncommitted batch — safe because ingestion is idempotent.
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    last_message = time.monotonic()
    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                if time.monotonic() - last_message > idle_timeout:
                    return
                continue
            if message.error():
                continue
            last_message = time.monotonic()
            yield json.loads(message.value())
            consumer.commit(message, asynchronous=True)
    finally:
        consumer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="streaming.consumer")
    parser.add_argument("--source", required=True, help="path to NDJSON, '-' for stdin, or 'kafka'")
    parser.add_argument("--batch-size", type=int, default=10_000)
    parser.add_argument("--flush-ms", type=int, default=500)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="betslips")
    parser.add_argument("--group", default="betflow-consumer")
    parser.add_argument("--idle-timeout", type=float, default=10.0)
    parser.add_argument("--stats-interval", type=float, default=5.0)
    args = parser.parse_args(argv)

    inserter = Inserter(url=args.url)
    events = (
        iter_kafka(args.brokers, args.topic, args.group, args.idle_timeout)
        if args.source == "kafka"
        else iter_file(args.source)
    )

    batch: list[dict] = []
    started = time.monotonic()
    last_flush = started
    next_stats = started + args.stats_interval
    seen = 0

    for event in events:
        batch.append(to_row(event))
        seen += 1

        now = time.monotonic()
        if len(batch) >= args.batch_size or (now - last_flush) * 1000 >= args.flush_ms:
            inserter.send(batch)
            batch.clear()
            last_flush = now

        if now >= next_stats:
            elapsed = now - started
            print(
                f"[consumer] {seen:,} events | {seen / elapsed:,.0f} ev/s "
                f"| {inserter.stats.batches} batches | parts {inserter.part_count()}",
                file=sys.stderr,
            )
            next_stats = now + args.stats_interval

    inserter.send(batch)

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
