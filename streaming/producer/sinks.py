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
                # The default queue is 100,000 messages. At the brief's ceiling
                # the producer hands over 8,333/s in 0.05s slices, and a broker
                # pausing for even a second puts the queue within reach of full
                # — at which point produce() raises BufferError. Raised, and the
                # BufferError still handled below, because a queue limit is a
                # backpressure signal rather than an error to configure away.
                "queue.buffering.max.messages": 500_000,
            }
        )

    def write(self, events: list) -> None:
        for event in events:
            # `uid` is the partition key: confluent-kafka hashes it (murmur2)
            # to choose the partition, so every event for one customer lands in
            # one partition and per-Uid order holds (ADR-0013). The
            # sharp-behaviour and repeat-backing analyses both group by Uid and
            # depend on it.
            #
            # The event is a dataclass, and `as_dict()` is where the wire shape
            # is decided — reading `event.uid` directly would bypass whatever
            # naming that mapping applies, so the payload is built first and the
            # key taken from it.
            payload = event.as_dict()
            while True:
                try:
                    self._producer.produce(
                        self._topic,
                        key=str(payload["uid"]).encode(),
                        value=json.dumps(payload, separators=(",", ":")).encode(),
                    )
                    break
                except BufferError:
                    # The local queue is full: the broker is not draining as
                    # fast as this loop fills. Serve callbacks and retry rather
                    # than dropping the event — silently losing events would
                    # make every throughput figure here meaningless.
                    self._producer.poll(0.1)
        # Serve delivery callbacks without blocking; poll(0) is the documented
        # way to keep the internal queue draining.
        self._producer.poll(0)

    def flush(self) -> None:
        # flush() returns the number of messages still undelivered. Ignoring it
        # is how a run reports events it never actually sent.
        remaining = self._producer.flush(30)
        if remaining:
            raise SystemExit(f"kafka: {remaining} messages undelivered after 30s flush")

    def close(self) -> None:
        self.flush()


def build(spec: str, brokers: str, topic: str) -> Sink:
    """`stdout`, `file:<path>`, or `kafka`."""
    if spec == "stdout":
        return StreamSink(sys.stdout)
    if spec.startswith("file:"):
        return StreamSink(open(spec[5:], "w"))
    if spec == "kafka":
        return KafkaSink(brokers, topic)
    raise SystemExit(f"unknown sink: {spec!r} (expected stdout, file:<path>, or kafka)")
