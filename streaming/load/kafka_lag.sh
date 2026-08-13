#!/usr/bin/env bash
# Consumer lag, read from the broker rather than from the consumer.
#
# This is the ADR-0013 argument made operational: lag is
# `log-end-offset - committed-offset`, computed by Kafka from facts it owns. A
# consumer reporting its own backlog is the component under suspicion vouching
# for itself, so nothing here asks the consumer anything.
#
# Usage: streaming/load/kafka_lag.sh [group] [samples] [interval_seconds]

set -uo pipefail

GROUP="${1:-betflow-consumer}"
SAMPLES="${2:-30}"
INTERVAL="${3:-2}"

describe() {
  docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
      --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null
}

printf "%8s  %12s  %12s  %10s  %8s\n" "elapsed" "committed" "log-end" "LAG" "members"
start=$SECONDS
for _ in $(seq "$SAMPLES"); do
  out=$(describe)
  # Sum across partitions. Rows with a '-' offset are partitions the group has
  # never committed to; they count as 0 consumed, not as missing.
  read -r cur end lag members <<<"$(echo "$out" | awk '
      /^'"$GROUP"'/ {
          c += ($4 == "-" ? 0 : $4); e += $5; l += ($6 == "-" ? $5 : $6);
          if ($7 != "-" && $7 != "") m[$7] = 1
      }
      END { n = 0; for (k in m) n++; printf "%d %d %d %d", c, e, l, n }')"
  printf "%7ss  %12s  %12s  %10s  %8s\n" "$((SECONDS - start))" "$cur" "$end" "$lag" "$members"
  sleep "$INTERVAL"
done
