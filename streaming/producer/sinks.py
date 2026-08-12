"""Where generated events go.

The producer is sink-abstracted so branch 1 is testable without a broker running:
every calibration and rate test in `docs/build/01-producer.md` uses the file
sink. Kafka is the production path (ADR-0013).
"""

from __future__ import annotations

import json
import sys
from typing import Protocol


class Sink(Protocol):
    def write(self, events: list) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


class StreamSink:
    """NDJSON to an open stream. Used for stdout and for file output."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def write(self, events: list) -> None:
        # One json.dumps per event, joined once: measured at 267k ev/s, which is
        # 32x the 8,333 ev/s the brief's ceiling requires.
        self._stream.write(
            "".join(json.dumps(e.as_dict(), separators=(",", ":")) + "\n" for e in events)
        )

    def flush(self) -> None:
        self._stream.flush()

    def close(self) -> None:
        if self._stream not in (sys.stdout, sys.stderr):
            self._stream.close()


class KafkaSink:
    """Kafka producer, partitioned by uid (ADR-0013).

    Partitioning by `hash(uid)` keeps all of one customer window's activity in one
    partition, so per-Uid ordering holds without a global order — which the
    sharp-behaviour and repeat-backing analyses both depend on, since they group
    by Uid.

    The client library is imported lazily so the file and stdout sinks work on a
    machine with no Kafka client installed.
    """

    def __init__(self, brokers: str, topic: str) -> None:
        try:
            from confluent_kafka import Producer  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "confluent-kafka is not installed. Either `pip install confluent-kafka` "
                "or use --sink file/stdout, which every producer test uses."
            ) from exc

        self._topic = topic
        self._producer = Producer(
            {
                "bootstrap.servers": brokers,
                # Batch aggressively: at 8,333 ev/s the per-message overhead
                # dominates otherwise.
                "linger.ms": 50,
                "batch.size": 1 << 20,
                "compression.type": "lz4",
            }
        )

    def write(self, events: list) -> None:
        for event in events:
            self._producer.produce(
                self._topic,
                key=event.uid.encode(),
                value=json.dumps(event.as_dict(), separators=(",", ":")).encode(),
            )
        # Serve delivery callbacks without blocking; poll(0) is the documented
        # way to keep the internal queue draining.
        self._producer.poll(0)

    def flush(self) -> None:
        self._producer.flush()

    def close(self) -> None:
        self._producer.flush()


def build(spec: str, brokers: str, topic: str) -> Sink:
    """`stdout`, `file:<path>`, or `kafka`."""
    if spec == "stdout":
        return StreamSink(sys.stdout)
    if spec.startswith("file:"):
        return StreamSink(open(spec[5:], "w"))
    if spec == "kafka":
        return KafkaSink(brokers, topic)
    raise SystemExit(f"unknown sink: {spec!r} (expected stdout, file:<path>, or kafka)")
