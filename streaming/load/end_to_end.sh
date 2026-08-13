#!/usr/bin/env bash
# The whole pipeline at once, which is the only configuration that answers the
# brief's actual question.
#
#   producer -> Kafka -> consumer -> ClickHouse -> refresh (SQL) -> API -> Varnish -> 100 readers
#
# Every prior measurement isolated one hop. This runs all of them simultaneously
# and reports the three numbers that get confused with each other:
#
#   response latency  what a reader waits          (expect ~2ms)
#   data age          how stale the figure is      (bounded by the refresh tick)
#   end-to-end lag    placement -> visible on API  (never measured before)
#
# The last one is new. It is the number that answers "if I'm receiving millions
# of events, how fast does the front end see them?" — and it is the sum of
# ingest, refresh cadence and cache TTL, not any one of them.
#
# Usage: streaming/load/end_to_end.sh [rate_per_min] [duration_seconds]

set -uo pipefail
cd "$(dirname "$0")/../.."

RATE="${1:-500000}"
DURATION="${2:-60}"
DB="${DB:-srisk}"
CH="http://localhost:18123/?user=srisk&password=srisk&database=${DB}"
RESULTS="streaming/results"
mkdir -p "$RESULTS"

echo "═══════════════════════════════════════════════════════════════"
echo " end to end: ${RATE}/min through Kafka, 100 readers, ${DURATION}s"
echo "═══════════════════════════════════════════════════════════════"

rows_before=$(curl -s "$CH" --data-binary "SELECT count() FROM betslip_leg FORMAT TSV")
backend_before=$(docker exec srisk-varnish varnishstat -1 -f MAIN.backend_req 2>/dev/null | awk '{print $2}')
echo "rows before: ${rows_before}"

# Producer into Kafka. The consumer reads from the broker, so ingestion survives
# a consumer restart — the property the fifo path could not offer (ADR-0013).
python -m streaming.producer --rate "$RATE" --duration "$DURATION" \
    --reversal-share 0.02 --duplicate-share 0.01 \
    --sink kafka --brokers localhost:19092 --topic betslips \
    > "$RESULTS/_e2e_producer.log" 2>&1 &
PRODUCER=$!

python -m streaming.consumer --source kafka --brokers localhost:19092 \
    --topic betslips --group e2e-$(date +%s) --database "$DB" \
    --batch-size 20000 --flush-ms 1000 --idle-timeout 15 \
    > "$RESULTS/_e2e_consumer.log" 2>&1 &
CONSUMER=$!

# Refresh loops on class 1 — the SQL path, the cadence the dashboard reads.
(
  end=$((SECONDS + DURATION))
  while [ $SECONDS -lt $end ]; do
    python -m streaming.refresh --once --classes 1 --database "$DB" \
        --out streaming/out/artifacts >> "$RESULTS/_e2e_refresh.log" 2>&1
    sleep 2
  done
) &
REFRESH=$!

sleep 5   # let a first artifact exist before readers start

k6 run --quiet -e DURATION="$((DURATION - 8))s" streaming/load/k6_readers.js \
    > "$RESULTS/_e2e_k6.log" 2>&1
K6_STATUS=$?

wait $PRODUCER 2>/dev/null
wait $CONSUMER 2>/dev/null
wait $REFRESH 2>/dev/null

rows_after=$(curl -s "$CH" --data-binary "SELECT count() FROM betslip_leg FORMAT TSV")
backend_after=$(docker exec srisk-varnish varnishstat -1 -f MAIN.backend_req 2>/dev/null | awk '{print $2}')

echo
echo "── ingest: producer → Kafka → consumer → ClickHouse ──────────"
grep -E "^\[producer\] done" "$RESULTS/_e2e_producer.log" | tail -1
grep -E "^\[consumer\] done" "$RESULTS/_e2e_consumer.log" | tail -1
echo "rows: ${rows_before} → ${rows_after}  (+$((rows_after - rows_before)))"

echo
echo "── refresh: SQL aggregation, under write load ────────────────"
grep -oE "total [0-9.]+s" "$RESULTS/_e2e_refresh.log" | sed 's/total //;s/s//' | \
python3 -c "
import sys
v=[float(x) for x in sys.stdin if x.strip()]
print(f'  ticks {len(v)}  mean {sum(v)/len(v):.2f}s  min {min(v):.2f}s  max {max(v):.2f}s') if v else print('  no ticks recorded')"

echo
echo "── read: 100 concurrent, through Varnish ─────────────────────"
grep -E "http_req_duration|cache_hit_rate\.|http_reqs|http_req_failed" "$RESULTS/_e2e_k6.log" | head -4
echo "  backend fetches: $((backend_after - backend_before))"

echo
echo "── freshness: what the API actually serves ───────────────────"
curl -s http://localhost:18081/artifact/ops | python3 -c "
import json,sys
d=json.load(sys.stdin)
arts=d.get('artifacts',{})
for name in ('overview','flow','timing'):
    if name in arts:
        print(f\"  {name:<10} age {arts[name]['age_seconds']:>6.1f}s\")
print(f\"  watermark  {d.get('watermark')}\")
print(f\"  hash       {d.get('payload_hash')}\")
" 2>/dev/null || echo "  ops endpoint unavailable"

echo
[ $K6_STATUS -eq 0 ] && echo "THRESHOLDS PASSED" || echo "THRESHOLDS FAILED (see $RESULTS/_e2e_k6.log)"
