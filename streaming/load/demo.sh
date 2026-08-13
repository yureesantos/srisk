#!/usr/bin/env bash
# The scaling demo, as one command.
#
# Four acts, in the order they answer the brief:
#
#   1  the brief's rate       500k/min, everything green, lag flat
#   2  past the brief         raise until one consumer saturates and lag climbs
#   3  scale out              add consumers live; partitions rebalance, lag drains
#   4  what the reader saw    latency and freshness throughout
#
# Act 2 exists because of a measured awkwardness worth saying out loud rather
# than hiding: at the brief's 500k/min one consumer is not close to saturated
# (~31,600 ev/s against 8,333 required, 3.8x headroom), so lag stays flat and
# adding consumers demonstrates nothing. The rate is therefore driven above the
# brief deliberately. What that proves is the *mechanism* — not that 500k/min
# needs it.
#
#   streaming/load/demo.sh              # full run, ~4 minutes
#   streaming/load/demo.sh --act 3      # one act

set -uo pipefail
cd "$(dirname "$0")/../.."

DB="${DB:-srisk}"
CH="http://localhost:18123/?user=srisk&password=srisk&database=${DB}"
GROUP="demo-$(date +%s)"
TOPIC="${TOPIC:-betslips}"
BROKERS="${BROKERS:-localhost:19092}"
RESULTS="streaming/results"
ACT="all"
CLEAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --act) ACT="${2:-all}"; shift 2 ;;
    --clean) CLEAN=1; shift ;;
    *) shift ;;
  esac
done
mkdir -p "$RESULTS"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }
rule() { printf "%s\n" "────────────────────────────────────────────────────────────"; }

lag_now() {
  docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
      --bootstrap-server localhost:9092 --describe --group "$GROUP" 2>/dev/null |
    awk 'NR>1 && $6 ~ /^[0-9]+$/ {sum += $6} END {print sum+0}'
}

members_now() {
  docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
      --bootstrap-server localhost:9092 --describe --group "$GROUP" --members 2>/dev/null |
    # Column 2 is CONSUMER-ID; column 1 is the group name and is the same on
    # every row. Counting $1 reports 1 no matter how many members there are.
    awk 'NR>1 && NF>=5 {seen[$2]=1} END {print length(seen)}'
}

# ── act 1 ────────────────────────────────────────────────────────────────────
act_one() {
  bold "ACT 1 · the brief's rate — 500,000/min"
  rule
  echo "One consumer, 100 readers. The claim under test is that ingestion at the"
  echo "brief's ceiling does not move front-end latency."
  echo

  ./streaming/load/end_to_end.sh 500000 45 2>&1 |
    grep -E "producer\] done|consumer\] done|read p50|http_req_duration|cache_hit_rate\.|backend fetches|ticks|THRESHOLDS" |
    sed 's/^/  /'
}

# ── act 2 + 3 ────────────────────────────────────────────────────────────────
act_two_three() {
  bold "ACT 2 · past the brief — until one consumer saturates"
  rule
  echo "3.6M/min: 6.4x the brief's ceiling, chosen because one consumer sustains"
  echo "~31,600 ev/s and nothing below that produces a rising lag line."
  echo

  # Consumers from an interrupted earlier run stay in the group until their
  # session times out, and the member count then reads high while the group
  # rebalances them out. Clearing them makes the count mean what it says.
  pkill -f "streaming.consumer --source kafka" 2>/dev/null
  sleep 1

  python -m streaming.producer --rate 3600000 --duration 90 \
      --reversal-share 0.02 --duplicate-share 0.01 \
      --sink kafka --brokers "$BROKERS" --topic "$TOPIC" \
      > "$RESULTS/_demo_producer.log" 2>&1 &
  local producer=$!

  # A fresh consumer group starts at offset 0 and inherits every event still
  # retained in the topic — measured at ~9M from earlier runs — so the first lag
  # sample reads in the millions and the rise this act exists to show is already
  # over before it begins. Two ways out, and the default is the cheap one.
  if [ "$CLEAN" -eq 1 ]; then
    echo "  clearing the topic..."
    docker exec srisk-kafka /opt/kafka/bin/kafka-topics.sh \
        --bootstrap-server localhost:9092 --delete --topic "$TOPIC" >/dev/null 2>&1
    docker exec srisk-kafka /opt/kafka/bin/kafka-topics.sh \
        --bootstrap-server localhost:9092 --create --topic "$TOPIC" \
        --partitions 6 --replication-factor 1 >/dev/null 2>&1
    sleep 2
  else
    # Seek to the end instead of deleting: the demo measures what it produces,
    # the topic keeps its history, and repeated runs need no cleanup between
    # them. That retained history is also the evidence that the log absorbs
    # backlog — a consumer drained 2M rows against a 515k producer in the
    # end-to-end run precisely because it was there.
    docker exec srisk-kafka /opt/kafka/bin/kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 --group "$GROUP" --topic "$TOPIC" \
        --reset-offsets --to-latest --execute >/dev/null 2>&1
  fi

  python -m streaming.consumer --source kafka --brokers "$BROKERS" --topic "$TOPIC" \
      --group "$GROUP" --database "$DB" --batch-size 20000 --flush-ms 1000 \
      --idle-timeout 20 > "$RESULTS/_demo_consumer1.log" 2>&1 &

  printf "  %8s %12s %9s  %s\n" "elapsed" "LAG" "consumers" "event"
  local start=$SECONDS scaled=0
  # Sampled every 2s and scaled at 1.2M rather than 400k: at 3.6M/min the lag
  # crosses 400k in under four seconds, so a lower trigger scales before the
  # rise is visible and the demo loses its first act.
  while [ $((SECONDS - start)) -lt 130 ]; do
    local elapsed=$((SECONDS - start))
    local lag members
    lag=$(lag_now); members=$(members_now)
    local event=""

    # Scale once lag is unmistakably climbing — not on a timer, so the demo
    # reacts to the system rather than to a stopwatch.
    if [ "$scaled" -eq 0 ] && [ "${lag:-0}" -gt 1200000 ]; then
      bold "ACT 3 · scale out, without stopping anything"
      rule
      for i in 2 3; do
        python -m streaming.consumer --source kafka --brokers "$BROKERS" --topic "$TOPIC" \
            --group "$GROUP" --database "$DB" --batch-size 20000 --flush-ms 1000 \
            --idle-timeout 20 > "$RESULTS/_demo_consumer$i.log" 2>&1 &
      done
      scaled=1
      event="← two consumers added; producer never stopped"
      printf "  %8s %12s %9s  %s\n" "elapsed" "LAG" "consumers" "event"
    fi

    printf "  %7ss %12s %9s  %s\n" "$elapsed" "$(printf "%'d" "${lag:-0}")" "${members:-0}" "$event"

    if [ "$scaled" -eq 1 ] && [ "${lag:-1}" -eq 0 ]; then
      echo "  lag drained to zero"
      break
    fi
    sleep 2
  done

  wait $producer 2>/dev/null
  pkill -f "streaming.consumer --source kafka.*$GROUP" 2>/dev/null
}

# ── act 4 ────────────────────────────────────────────────────────────────────
act_four() {
  bold "ACT 4 · what the reader saw, throughout"
  rule
  curl -s http://localhost:18081/artifact/ops | python3 -c "
import json,sys
d=json.load(sys.stdin)
arts=d.get('artifacts',{})
for name in ('overview','flow','timing','prices','sharp'):
    if name in arts:
        a=arts[name]
        print(f\"  {name:<12} class {a['class']}   age {a['age_seconds']:>7.1f}s\")
print(f\"  watermark    {d.get('watermark')}\")
t=d.get('refresh_timing') or {}
if t: print(f\"  refresh      read {t.get('read_seconds')}s  analysis {t.get('analysis_seconds')}s\")
" 2>/dev/null || echo "  ops endpoint unavailable"

  echo
  echo "  Three numbers, and only the first is what a user waits for:"
  echo "    response latency   ~1.7 ms      what a reader waits"
  echo "    data age           2.8-5.9 s    how stale the screen is"
  echo "    recompute cost     background   what volume actually moves"
}

case "$ACT" in
  1) act_one ;;
  2|3) act_two_three ;;
  4) act_four ;;
  *) act_one; act_two_three; act_four ;;
esac

bold "done"
echo "Raw results: $RESULTS/*.md   ·   logs: $RESULTS/_demo_*.log"
