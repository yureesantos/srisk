"""End-to-end latency: emitted -> visible on the API.

Every other measurement covers one hop. This times a single identifiable event
through all of them:

    producer -> Kafka -> consumer -> ClickHouse -> refresh -> API -> Varnish

The figure it produces is the one that answers "if a bet is placed now, when
does the dashboard show it?" — and it is not the sum of the fastest paths. It is
dominated by the refresh cadence, because an event that lands in ClickHouse a
millisecond after a tick waits for the next one.

Method: emit a probe betslip with a unique customer id under continuous
background load, then poll the API until the artifact's row count includes it.
Uses the artifact the readers actually read, through the cache, not a direct
database query — otherwise it would measure a path no user takes.

    python -m streaming.load.latency_probe --probes 5
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from streaming.consumer.canonical import row_key  # noqa: E402
from streaming.producer.generate import Generator  # noqa: E402

CH = "http://localhost:18123"
API = "http://localhost:18081"


def ch_query(sql: str, database: str) -> str:
    params = urllib.parse.urlencode(
        {"user": "srisk", "password": "srisk", "database": database}
    )
    request = urllib.request.Request(f"{CH}/?{params}", data=sql.encode(), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode().strip()


def api_universe() -> dict:
    """Read through Varnish, as a reader would — not straight from the API."""
    with urllib.request.urlopen(f"{API}/artifact/overview", timeout=15) as response:
        body = json.loads(response.read())
    return {
        "legs": int(body["data"]["universe"]["legs"]),
        "watermark": body.get("watermark"),
        "age": float(response.headers.get("X-Artifact-Age-Seconds") or 0),
    }


def emit_probe(brokers: str, topic: str) -> tuple[str, int, int]:
    """One event with a unique uid, sent through the real producer path."""
    from confluent_kafka import Producer  # imported here so --help works without it

    generator = Generator(seed=1, expected_events=1)
    leg = generator.leg(int(time.time() * 1000))
    marker = f"probe-{uuid.uuid4().hex[:12]}"
    leg.uid = marker
    payload = leg.as_dict()

    producer = Producer({"bootstrap.servers": brokers, "linger.ms": 0})
    producer.produce(topic, key=marker.encode(), value=json.dumps(payload).encode())
    producer.flush(10)
    return marker, row_key(payload), payload["emitted_at"]


def main() -> int:
    parser = argparse.ArgumentParser(prog="latency_probe")
    parser.add_argument("--probes", type=int, default=5)
    parser.add_argument("--database", default="srisk")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="betslips")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    print(f"probing {args.probes}x — emitted → visible on the API\n")
    print(f"  {'#':<3} {'to ClickHouse':>14} {'to API':>10} {'artifact age':>13}")

    results = []
    for index in range(1, args.probes + 1):
        marker, key, version = emit_probe(args.brokers, args.topic)
        started = time.monotonic()

        # Stage 1: the consumer has written it.
        in_db = None
        while time.monotonic() - started < args.timeout:
            found = ch_query(
                f"SELECT count() FROM betslip_leg WHERE row_key = {key}", args.database
            )
            if found and int(found) > 0:
                in_db = time.monotonic() - started
                break
            time.sleep(0.05)

        if in_db is None:
            print(f"  {index:<3} {'timeout':>14}")
            continue

        # Stage 2: an artifact built *after* the probe landed. The test is the
        # watermark, not the row count: counts move constantly under background
        # load, so a rising count proves nothing about this event. The watermark
        # is the highest version the refresh saw, and the probe carries its own
        # emission time as its version — so an artifact whose watermark is at or
        # past it demonstrably includes the probe.
        visible = None
        while time.monotonic() - started < args.timeout:
            current = api_universe()
            if current["watermark"] and int(current["watermark"]) >= version:
                visible = time.monotonic() - started
                break
            time.sleep(0.2)

        age = api_universe()["age"]
        if visible is None:
            print(f"  {index:<3} {in_db * 1000:>13.0f}ms {'timeout':>10}")
        else:
            print(f"  {index:<3} {in_db * 1000:>13.0f}ms {visible:>9.1f}s {age:>12.1f}s")
            results.append((in_db, visible))

    if results:
        db = [r[0] for r in results]
        api = [r[1] for r in results]
        print()
        print(f"  to ClickHouse   median {sorted(db)[len(db) // 2] * 1000:.0f}ms")
        print(f"  to API          median {sorted(api)[len(api) // 2]:.1f}s   "
              f"min {min(api):.1f}s   max {max(api):.1f}s")
        print()
        print("  The second figure is dominated by the refresh cadence, not by")
        print("  transport: an event landing just after a tick waits for the next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
