# 2. Profile sharp *behaviour* in a window, not sharp *customers*

Date: 2026-07-23

## Status

Accepted

## Context

The most operationally valuable extension to the brief is identifying customers
who consistently capture price value — sharp bettors. It requires grouping
betslips by whoever placed them.

The only available grouping key is `Uid`, and the data shows it is **not** a
durable customer identifier:

- 10,405 distinct Uids across 72,742 betslips.
- Median activity span is **10 days**; 90% fall under 13 days — inside a dataset
  spanning 3.5 months. A real account would scatter activity across months.
- Uids are reused across fixtures and dates, and appear in two distinct formats
  (numeric, string) evidencing two source systems.

Volume is nonetheless concentrated enough to profile:

| Threshold | Uids | Share of turnover |
|---|---|---|
| ≥5 betslips | 3,816 | 79.9% |
| ≥10 betslips | 2,032 | 61.6% |
| ≥20 betslips | 788 | 42.3% |

So the population is analysable; the question is what a finding may claim.

## Decision

Score and report **sharp behaviour observed within a Uid's activity window**,
not sharp customer identity.

- The unit of analysis is a Uid, explicitly framed as *an activity window*, not
  a person.
- Minimum threshold of **10 betslips** to enter the scored population — covers
  61.6% of turnover while keeping per-Uid estimates meaningful.
- Every output naming a Uid states its betslip count and activity span, so the
  reader can judge the weight of the evidence themselves.
- No claim is made that two Uids are or are not the same person, and no
  cross-window customer history is constructed.

## Consequences

**Positive**

- The claim matches the evidence. A reviewer checking whether `Uid` is a
  customer id will find the limitation already stated rather than uncovering it.
- Still operationally useful: detecting a sharp pattern *in progress* is
  actionable for a trading desk regardless of whether the individual is known.
- Keeps the door open — if the client later supplies a real account id, the same
  scoring runs unchanged on a better key.

**Negative**

- Cannot answer "is this the same person who beat us last month?" — the question
  a risk team would most want answered.
- Lifetime-value and long-horizon loyalty analysis are off the table.
- A genuinely sharp actor spreading activity across several Uids would be
  scored as several unremarkable windows rather than one strong signal. This is
  a real detection gap and is stated as such in the report.
