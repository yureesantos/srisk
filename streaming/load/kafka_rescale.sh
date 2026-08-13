#!/usr/bin/env bash
# The scaling demo: lag rises, consumers are added live, lag drains.
#
# The honest difficulty this script exists to handle: at the brief's ceiling
# (8,333 ev/s) one consumer is nowhere near saturated — measured at ~31,600 ev/s,
# 3.8x the requirement — so a producer running at the ceiling produces a flat lag
# line and adding consumers demonstrates nothing. Lag only rises if the producer
# is driven ABOVE one consumer's drain rate.
#
# So the rate here is deliberately above the brief. That is the point: the demo
# needs a saturated consumer to be a demo at all, and saying so is more useful
# than showing a rescale against a backlog that never existed. What the run
# proves is the mechanism — partitions rebalance onto new members without a
# restart, and lag drains once they do — not that the brief's rate needs it.
#
# Usage: streaming/load/kafka_rescale.sh [rate_per_min] [duration_seconds]

set -uo pipefail
cd "$(dirname "$0")/../.."

RATE="${1:-3600000}"     # 60,000 ev/s: roughly 2x one consumer's drain rate
DURATION="${2:-90}"
GROUP=rescale-demo
RESULTS="streaming/results"
mkdir -p "$RESULTS"

lag_now() {
  docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
      --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null \
    | awk '/^'"$GROUP"'/ { l += ($6 == "-" ? $5 : $6); if ($7 != "-" && $7 != "") m[$7]=1 }
           END { n=0; for (k in m) n++; printf "%d %d", l, n }'
}

echo "══════════════════════════════════════════════════════════"
echo " live rescale: ${RATE}/min for ${DURATION}s, 1 -> 3 consumers"
echo "══════════════════════════════════════════════════════════"

export CONSUMER_GROUP="$GROUP"

# One consumer to begin with. --force-recreate because a container left over
# from an earlier run keeps that run's environment: compose sees no image change
# and reuses it, so the replica silently joins the previous group and its offsets
# never move. That failure reads exactly like a stalled consumer on the lag
# graph, which cost a full debugging cycle to attribute correctly.
docker compose -f streaming/docker-compose.yml --profile scale up -d \
    --force-recreate --scale consumer=1 consumer > /dev/null 2>&1

# Wait for the replica to actually be consuming rather than sleeping a guess:
# first start pulls the image and pip-installs the Kafka client.
echo "waiting for consumer 1 to join..."
for _ in $(seq 60); do
  read -r _ members <<<"$(lag_now)"
  [ "${members:-0}" -ge 1 ] && break
  sleep 2
done

python -m streaming.producer --rate "$RATE" --duration "$DURATION" \
    --reversal-share 0.02 --duplicate-share 0.01 \
    --sink kafka --brokers localhost:19092 --topic betslips \
    > "$RESULTS/_producer.log" 2>&1 &
PRODUCER=$!

printf "\n%8s  %10s  %8s  %s\n" "elapsed" "LAG" "members" "event"
start=$SECONDS
scaled=0
while kill -0 $PRODUCER 2>/dev/null || [ $((SECONDS - start)) -lt $((DURATION + 60)) ]; do
  read -r lag members <<<"$(lag_now)"
  note=""
  # Scale up once, a third of the way in, while the producer is still running.
  if [ $scaled -eq 0 ] && [ $((SECONDS - start)) -ge $((DURATION / 3)) ]; then
    # No --force-recreate here, and that is the point: replica 1 keeps running
    # untouched while 2 and 3 are added. The producer is not stopped either.
    docker compose -f streaming/docker-compose.yml --profile scale up -d \
        --scale consumer=3 consumer > /dev/null 2>&1
    scaled=1
    note="<-- scaled to 3, no restart of anything else"
  fi
  printf "%7ss  %10s  %8s  %s\n" "$((SECONDS - start))" "$lag" "$members" "$note"
  # Stop once the producer is done and the backlog is gone.
  if ! kill -0 $PRODUCER 2>/dev/null && [ "${lag:-1}" -eq 0 ] && [ $scaled -eq 1 ]; then
    echo "lag drained to 0"
    break
  fi
  sleep 3
done

wait $PRODUCER 2>/dev/null
echo
grep -E "^\[producer\] done" "$RESULTS/_producer.log" | tail -1
echo
echo "── final assignment, per partition ───────────────────────"
docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null
