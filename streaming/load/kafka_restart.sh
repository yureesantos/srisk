#!/usr/bin/env bash
# Kill the consumer mid-stream, restart it, and show the table converges.
#
# The property under test is ADR-0007's: ingestion is idempotent, so the batch
# that was in flight when the process died replays on restart and collapses to
# the same state rather than double-counting. That is what makes
# commit-after-insert safe — the consumer deliberately acknowledges late, and
# accepts replay as the cost.
#
# The comparison is the fingerprint, not the row count alone: a count can match
# while values differ, and `sum(cityHash64(...))` over the collapsed table
# catches that.
#
# Usage: streaming/load/kafka_restart.sh [events]

set -uo pipefail
cd "$(dirname "$0")/../.."

EVENTS="${1:-1500000}"
GROUP=restart-demo
CH='http://localhost:18123/?user=srisk&password=srisk&database=srisk'
FP='SELECT count(), sum(cityHash64(row_key, version, turnover, ggr, net_revenue)) FROM srisk.betslip_leg FINAL FORMAT TSV'

echo "══════════════════════════════════════════════════════════"
echo " idempotency across a restart: ${EVENTS} events"
echo "══════════════════════════════════════════════════════════"

curl -s "$CH" --data-binary 'TRUNCATE TABLE srisk.betslip_leg' > /dev/null
docker exec srisk-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
    --delete --topic betslips > /dev/null 2>&1
sleep 3
docker exec srisk-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
    --create --topic betslips --partitions 6 --replication-factor 1 > /dev/null 2>&1

echo "── filling the log ───────────────────────────────────────"
python -m streaming.producer --count "$EVENTS" --rate 3000000 --seed 99 \
    --reversal-share 0.02 --duplicate-share 0.01 \
    --sink kafka --brokers localhost:19092 --topic betslips 2>&1 | grep done

run_consumer() {
  python -m streaming.consumer --source kafka --brokers localhost:19092 \
      --topic betslips --group "$GROUP" \
      --batch-size 20000 --flush-ms 1000 --idle-timeout "$1"
}

echo
echo "── consumer, killed mid-stream ───────────────────────────"
run_consumer 20 > /tmp/_restart_1.log 2>&1 &
PID=$!
# Long enough to have inserted and committed several batches, short enough that
# a large remainder is still uncommitted when the process dies.
sleep 12
kill -9 $PID 2>/dev/null
wait $PID 2>/dev/null
echo "killed -9 after 12s (SIGKILL: no chance to flush or commit)"
rows_mid=$(curl -s "$CH" --data-binary "SELECT count() FROM srisk.betslip_leg FORMAT TSV")
echo "rows at kill: ${rows_mid}"
echo "lag at kill:"
docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null \
  | awk '/^'"$GROUP"'/ {c+=$4; e+=$5; l+=($6=="-"?$5:$6)} END {printf "  committed %d / log-end %d / LAG %d\n", c, e, l}'

echo
echo "── restart, drain to the end ─────────────────────────────"
run_consumer 15 2>&1 | grep done
FP1=$(curl -s "$CH" --data-binary "$FP")
echo "fingerprint after restart : ${FP1}"

echo
echo "── full replay from offset 0, into the same table ────────"
# Same events, delivered a second time to a table that already holds them. If
# ingestion is idempotent this changes nothing at all.
#
# --reset-offsets refuses to act on a group with live members, and it fails
# *quietly* into a run that consumes nothing — which then "converges" trivially
# and proves nothing. So the reset is verified rather than assumed.
# Bounded: the group coordinator can take session.timeout.ms to notice a member
# has gone, and an unbounded wait here turns a slow expiry into a hung script.
for _ in $(seq 40); do
  docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
      --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null \
    | grep -q "has no active members" && break
  sleep 3
done
docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --group "$GROUP" --topic betslips \
    --reset-offsets --to-earliest --execute > /dev/null 2>&1
after_reset=$(docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null \
  | awk '/^'"$GROUP"'/ {c += ($4 == "-" ? 0 : $4)} END {print c+0}')
echo "committed offset after reset: ${after_reset}  (must be 0 for the replay to mean anything)"

replayed=$(run_consumer 15 2>&1 | grep done | tee /dev/stderr | grep -oE '^\[consumer\] done: [0-9,]+' | grep -oE '[0-9,]+$')
if [ "${replayed//,/}" = "0" ]; then
  echo "REPLAY CONSUMED NOTHING - the comparison below is vacuous"
fi
FP2=$(curl -s "$CH" --data-binary "$FP")
echo "fingerprint after replay  : ${FP2}"

echo
if [ "$FP1" = "$FP2" ]; then
  echo "CONVERGED: replay changed nothing (${FP1})"
else
  echo "DIVERGED: ${FP1} != ${FP2}"
fi
