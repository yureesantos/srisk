#!/usr/bin/env bash
# Does read latency hold while data is arriving continuously?
#
# Every measurement so far ran the stages sequentially: ingest, then refresh,
# then read. That answers a question nobody asked. The real one is whether the
# front end stays fast **while** the pipeline is under sustained write load —
# which is the entire premise of the exercise.
#
# Runs simultaneously for the configured duration:
#   producer  -> emitting at the dialled rate
#   consumer  -> canonicalising and inserting
#   refresh   -> recomputing class 1 on its cadence
#   k6        -> 100 concurrent readers against Varnish
#
# Usage: streaming/load/concurrent_test.sh [rate_per_min] [duration_seconds]

set -uo pipefail
cd "$(dirname "$0")/../.."

RATE="${1:-500000}"
DURATION="${2:-60}"
CH='http://localhost:18123/?user=srisk&password=srisk&database=srisk'
RESULTS="streaming/results"
mkdir -p "$RESULTS"

echo "══════════════════════════════════════════════════════════"
echo " concurrent load: ${RATE}/min ingest + 100 readers, ${DURATION}s"
echo "══════════════════════════════════════════════════════════"

rows_before=$(curl -s "$CH" --data-binary "SELECT count() FROM srisk.betslip_leg FORMAT TSV")
backend_before=$(docker exec srisk-varnish varnishstat -1 -f MAIN.backend_req 2>/dev/null | awk '{print $2}')
echo "rows before: ${rows_before}"

# Producer writes to a fifo the consumer drains, so ingestion is genuinely
# streaming rather than a file being replayed after the fact.
FIFO=$(mktemp -u); mkfifo "$FIFO"

python -m streaming.producer --rate "$RATE" --duration "$DURATION" \
    --reversal-share 0.02 --duplicate-share 0.01 --sink "file:$FIFO" \
    > "$RESULTS/_producer.log" 2>&1 &
PRODUCER=$!

python -m streaming.consumer --source "$FIFO" --batch-size 20000 --flush-ms 1000 \
    > "$RESULTS/_consumer.log" 2>&1 &
CONSUMER=$!

# Refresh loops on class 1 — the cadence the dashboard actually reads.
(
  end=$((SECONDS + DURATION))
  while [ $SECONDS -lt $end ]; do
    python -m streaming.refresh --once --classes 1 --out streaming/out/artifacts \
        >> "$RESULTS/_refresh.log" 2>&1
    sleep 1
  done
) &
REFRESH=$!

sleep 3   # let ingestion get underway before readers start

k6 run --quiet -e DURATION="$((DURATION - 5))s" streaming/load/k6_readers.js \
    > "$RESULTS/_k6.log" 2>&1
K6_STATUS=$?

wait $PRODUCER 2>/dev/null
wait $CONSUMER 2>/dev/null
wait $REFRESH 2>/dev/null
rm -f "$FIFO"

rows_after=$(curl -s "$CH" --data-binary "SELECT count() FROM srisk.betslip_leg FORMAT TSV")
backend_after=$(docker exec srisk-varnish varnishstat -1 -f MAIN.backend_req 2>/dev/null | awk '{print $2}')

echo
echo "── ingest ────────────────────────────────────────────────"
grep -E "^\[producer\] done" "$RESULTS/_producer.log" | tail -1
grep -E "^\[consumer\] done" "$RESULTS/_consumer.log" | tail -1
echo "rows: ${rows_before} -> ${rows_after}  (+$((rows_after - rows_before)))"
echo
echo "── refresh, under write load ─────────────────────────────"
grep -oE "total [0-9.]+s" "$RESULTS/_refresh.log" | awk '{gsub("s","",$2); t[NR]=$2; s+=$2}
    END {n=asort(t); printf "  ticks %d   mean %.2fs   min %.2fs   max %.2fs\n", NR, s/NR, t[1], t[n]}'
echo
echo "── read latency, while all of the above was happening ────"
grep -E "http_req_duration|cache_hit_rate|http_reqs|http_req_failed" "$RESULTS/_k6.log" | head -4
echo "backend fetches: $((backend_after - backend_before))"
echo
[ $K6_STATUS -eq 0 ] && echo "THRESHOLDS PASSED" || echo "THRESHOLDS FAILED (see $RESULTS/_k6.log)"
