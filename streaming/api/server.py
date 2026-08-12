"""Artifact API. Serves files the refresh job wrote; computes nothing.

ADR-0011 makes the case: the cache in front is not protecting an expensive
computation from repetition — the refresh job already did the work on its own
cadence. The cache is fanning **one** artifact out to many readers. So the API's
whole job is to return the current file with the right `Cache-Control`, and its
being trivial is what keeps it horizontally scalable (ADR-0010).

Cache policy is per class, verbatim from ADR-0011, because the classes have
different freshness by measurement rather than by preference:

    class 1  max-age=2, stale-while-revalidate=5   placement-complete, immutable
    class 2  max-age=30                            settlement churn measured at 95s
    class 3  max-age=300 + BAN on window close     defined over a closed window

`stale-while-revalidate` on class 1 is what keeps a reader from ever waiting on
a refresh: an expired-but-recent artifact is served immediately while the new one
is fetched behind it.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Artifact -> class. Mirrors CLASS_ARTIFACTS in the refresh job; `data_quality`
# sits in class 2 because it reports price coverage.
ARTIFACT_CLASS = {
    "overview": 1,
    "flow": 1,
    "timing": 1,
    "prices": 2,
    "data_quality": 2,
    "concentration": 3,
    "anomalies": 3,
    "sharp": 3,
    "meta": 1,
}

CACHE_CONTROL = {
    1: "public, max-age=2, stale-while-revalidate=5",
    2: "public, max-age=30",
    3: "public, max-age=300",
}


class Handler(BaseHTTPRequestHandler):
    artifacts: Path = Path()
    protocol_version = "HTTP/1.1"

    # Silence per-request logging: at 100 concurrent readers it would dominate
    # the terminal and slow the very thing being measured.
    def log_message(self, *args) -> None:
        return

    def do_GET(self) -> None:
        path = self.path.split("?")[0].rstrip("/")

        if path in ("/health", "/"):
            return self._send(b'{"status":"ok"}', "no-store")

        if path == "/artifact/ops":
            return self._send(json.dumps(self._ops()).encode(), "no-store")

        if not path.startswith("/artifact/"):
            return self._send(b'{"error":"not found"}', "no-store", status=404)

        name = path.rsplit("/", 1)[-1]
        if name not in ARTIFACT_CLASS:
            return self._send(b'{"error":"unknown artifact"}', "no-store", status=404)

        file = self.artifacts / f"{name}.json"
        if not file.exists():
            # A class that has not run yet is a 503, not a 404: the artifact is
            # expected to exist shortly, and a cache must not remember a 404.
            return self._send(b'{"error":"not yet generated"}', "no-store", status=503)

        body = file.read_bytes()
        self._send(body, CACHE_CONTROL[ARTIFACT_CLASS[name]], extra={
            # The freshness ADR-0009 promises, carried on the response itself so
            # a reader can see it without opening the payload.
            "X-Artifact-Class": str(ARTIFACT_CLASS[name]),
            "X-Artifact-Age-Seconds": f"{time.time() - file.stat().st_mtime:.1f}",
        })

    def _ops(self) -> dict:
        """Operations feed: what the dashboard panel and the demo read."""
        entries = {}
        for name, klass in ARTIFACT_CLASS.items():
            file = self.artifacts / f"{name}.json"
            if file.exists():
                entries[name] = {
                    "class": klass,
                    "age_seconds": round(time.time() - file.stat().st_mtime, 1),
                    "bytes": file.stat().st_size,
                }
        meta_file = self.artifacts / "meta.json"
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        return {
            "artifacts": entries,
            "watermark": meta.get("watermark"),
            "identities": meta.get("identities"),
            "pending_supersedence": meta.get("pending_supersedence"),
            "payload_hash": meta.get("payload_hash"),
            "refresh_timing": meta.get("timing"),
            "served_at": time.time(),
        }

    def _send(self, body: bytes, cache_control: str, status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(prog="streaming.api")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8088)
    args = parser.parse_args()

    Handler.artifacts = args.artifacts
    # Threading matters here and nowhere else in this service: 100 concurrent
    # readers against a single-threaded server would queue behind each other and
    # the measurement would be of the server's accept loop, not of the cache.
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"[api] serving {args.artifacts} on :{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
