#!/usr/bin/env bash
# Producer -> Kafka -> consumer -> ClickHouse, at the brief's ceiling.
#
# The comparison this exists to make: the fifo baseline (05-concurrent.md)
# sustained 8,591 ev/s with a direct pipe between the two processes. Inserting a
# broker into that path costs something, and the point is to measure the cost
# rather than assume it is negligible — ADR-0013 justifies the log on
# observability, not speed, so a throughput regression here is a finding to
# record, not a failure to hide.
#
# Lag is sampled from the broker throughout, in the background.
#
# Usage: streaming/load/kafka_test.sh [rate_per_min] [duration_seconds]

set -uo pipefail
cd "$(dirname "$0")/../.."

RATE="${1:-500000}"
DURATION="${2:-60}"
CH='http://localhost:18123/?user=srisk&password=srisk&database=srisk'
RESULTS="streaming/results"
FP='SELECT count(), sum(cityHash64(row_key, version, turnover, ggr, net_revenue)) FROM srisk.betslip_leg FINAL FORMAT TSV'
mkdir -p "$RESULTS"

echo "══════════════════════════════════════════════════════════"
echo " kafka path: ${RATE}/min for ${DURATION}s"
echo "══════════════════════════════════════════════════════════"

rows_before=$(curl -s "$CH" --data-binary "SELECT count() FROM srisk.betslip_leg FORMAT TSV")
echo "rows before: ${rows_before}"

# Sample lag from the broker while the run happens.
streaming/load/kafka_lag.sh betflow-consumer $((DURATION / 2 + 10)) 2 \
    > "$RESULTS/_lag.log" 2>&1 &
LAG=$!

python -m streaming.consumer --source kafka --brokers localhost:19092 \
    --topic betslips --group betflow-consumer \
    --batch-size 20000 --flush-ms 1000 --idle-timeout 15 \
    > "$RESULTS/_consumer.log" 2>&1 &
CONSUMER=$!

sleep 2   # let the consumer join the group before the producer starts

python -m streaming.producer --rate "$RATE" --duration "$DURATION" \
    --reversal-share 0.02 --duplicate-share 0.01 \
    --sink kafka --brokers localhost:19092 --topic betslips \
    > "$RESULTS/_producer.log" 2>&1
PRODUCER_STATUS=$?

echo "producer finished; waiting for the consumer to drain"
wait $CONSUMER 2>/dev/null
kill $LAG 2>/dev/null

rows_after=$(curl -s "$CH" --data-binary "SELECT count() FROM srisk.betslip_leg FORMAT TSV")

echo
echo "── producer -> kafka ─────────────────────────────────────"
grep -E "^\[producer\] done" "$RESULTS/_producer.log" | tail -1
echo
echo "── kafka -> consumer -> clickhouse ───────────────────────"
grep -E "^\[consumer\] done" "$RESULTS/_consumer.log" | tail -1
echo "rows: ${rows_before} -> ${rows_after}  (+$((rows_after - rows_before)))"
echo
echo "── lag, from the broker ──────────────────────────────────"
cat "$RESULTS/_lag.log"
echo
echo "── final offsets ─────────────────────────────────────────"
docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --describe --group betflow-consumer 2>/dev/null
echo
echo "── fingerprint ───────────────────────────────────────────"
curl -s "$CH" --data-binary "$FP"
[ $PRODUCER_STATUS -eq 0 ] || echo "PRODUCER FAILED (see $RESULTS/_producer.log)"
