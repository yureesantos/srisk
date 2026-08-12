"""Betslip producer with a rate dial.

    python -m streaming.producer --rate 70000  --duration 10 --sink stdout
    python -m streaming.producer --rate 500000 --duration 60 --sink kafka
    python -m streaming.producer --count 500000 --seed 42 --sink file:/tmp/fixture.ndjson

`--rate` is per minute, matching the brief's vocabulary (70k/min to 500k/min).
The dial controls emission rate **only** — never the shape of the data. That
separation is what makes a rate change interpretable: if a metric moves when the
rate moves, it is the system responding, not the data changing underneath
(DESIGN-STREAMING).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from .generate import Generator
from .sinks import build

# Emission is paced in short slices rather than per event: sleeping per event at
# 8,333 ev/s would spend more time in the scheduler than in generation.
SLICE_SECONDS = 0.05


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="streaming.producer")
    parser.add_argument(
        "--rate", type=int, default=70_000, help="events per minute (default 70000)"
    )
    parser.add_argument("--duration", type=float, help="seconds to run")
    parser.add_argument("--count", type=int, help="total events to emit (overrides --duration)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--reversal-share",
        type=float,
        default=0.02,
        help="share of legs later superseded by a settlement reversal (ADR-0007)",
    )
    parser.add_argument(
        "--duplicate-share",
        type=float,
        default=0.01,
        help="share of events delivered twice; the exports already carry 36,832 "
        "and 17,253 exact duplicates",
    )
    parser.add_argument("--sink", default="stdout", help="stdout | file:<path> | kafka")
    parser.add_argument("--brokers", default="localhost:19092")
    parser.add_argument("--topic", default="betslips")
    parser.add_argument(
        "--stats-interval", type=float, default=5.0, help="seconds between stderr stats"
    )
    args = parser.parse_args(argv)

    if not args.duration and not args.count:
        args.duration = 10.0

    # The Uid pool scales with expected volume so the legs-per-Uid ratio — and
    # therefore the concentration metrics — hold regardless of run length.
    expected = args.count or int(args.rate / 60.0 * (args.duration or 10.0))

    generator = Generator(
        seed=args.seed,
        reversal_share=args.reversal_share,
        duplicate_share=args.duplicate_share,
        expected_events=max(1, expected),
    )
    sink = build(args.sink, args.brokers, args.topic)

    per_slice = max(1, round(args.rate / 60.0 * SLICE_SECONDS))
    started = time.monotonic()
    deadline = started + args.duration if args.duration else None

    emitted = 0
    stop = False

    def handle_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    next_stats = started + args.stats_interval
    last_emitted, last_stats_at = 0, started

    try:
        slice_index = 0
        while not stop:
            now = time.monotonic()
            if deadline and now >= deadline:
                break
            if args.count and emitted >= args.count:
                break

            batch = []
            budget = per_slice
            if args.count:
                budget = min(budget, args.count - emitted)
            # emit() can return more than one event per draw (duplicates,
            # reversals), so the budget counts *draws* and the actual emission
            # can exceed it slightly. The dial therefore governs placements, and
            # corrections ride on top — which is the honest reading of "rate".
            for _ in range(budget):
                batch.extend(generator.emit(int(time.time() * 1000)))

            sink.write(batch)
            emitted += len(batch)

            # Pace against absolute slice boundaries rather than sleeping a fixed
            # amount: sleeping SLICE_SECONDS per iteration accumulates the
            # generation time as drift, and the measured rate drifts below the dial.
            slice_index += 1
            target = started + slice_index * SLICE_SECONDS
            drift = target - time.monotonic()
            if drift > 0:
                time.sleep(drift)

            now = time.monotonic()
            if now >= next_stats:
                window = now - last_stats_at
                rate = (emitted - last_emitted) / window if window else 0.0
                print(
                    f"[producer] {emitted:,} events | {rate:,.0f} ev/s "
                    f"| {rate * 60:,.0f}/min | dial {args.rate:,}/min",
                    file=sys.stderr,
                )
                last_emitted, last_stats_at = emitted, now
                next_stats = now + args.stats_interval
    finally:
        sink.flush()
        sink.close()

    elapsed = time.monotonic() - started
    achieved = emitted / elapsed if elapsed else 0.0
    print(
        f"[producer] done: {emitted:,} events in {elapsed:.1f}s "
        f"= {achieved:,.0f} ev/s ({achieved * 60:,.0f}/min)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
