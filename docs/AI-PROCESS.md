# How this was built

A record of the AI-assisted process behind both components, written because it
was asked for and because the answer is the same one the rest of this repository
gives about its numbers: *here is where it came from.*

The tool was **Claude Code** (Anthropic's CLI agent), driven from a terminal in
this repository. Everything below is reconstructed from the actual session
history. The prompts were typed in Portuguese and are translated here; the
translations are faithful, including the blunt ones.

---

## How I work with it

Three habits shaped this repository more than any individual prompt.

**Interview before implementation.** Nothing was written until the problem was
pinned down out loud. The first substantial instruction was not "build a
dashboard" — it was a request to be interrogated about the plan, one question at
a time, with the constraint that any question answerable from the data had to be
answered by reading the data instead of asking me. That session produced
`CONTEXT.md` (the glossary) and the first architecture decision records before a
single line of analysis code existed.

**Plan in a separate context, then implement.** For every non-trivial piece I
spawned a dedicated planning agent that could only read — no writes — so the plan
had to survive on its own merits before anything was built. Eleven of those ran
across the project. The pattern shows up verbatim in the history: *"spawn an
agent with Fable and plan first."*

**Reject output that isn't good enough.** The dashboard was rebuilt twice
because I did not accept what came back. Those rejections are quoted below
unedited — they are the most honest part of this document.

### Tooling

| | |
|---|---|
| Agent | Claude Code |
| Models | Opus (implementation), Fable (planning agents) |
| Planning agents | 11, read-only, one per subsystem |
| Skills used | `grill-with-docs` (requirements interview), `impeccable` (frontend craft), `dataviz` (chart/colour method), Matt Pocock's engineering skills (domain modelling, ADRs) |

A note on the skills, since they are third-party and worth naming honestly:
`grill-with-docs` is what forced the interview-first approach and the ADR
discipline; `dataviz` is where the palette validation script came from, which is
why `DESIGN.md` can show a passing colour-blindness check rather than an
assertion of good taste; `impeccable` supplied the frontend craft standards. They
set the *method*. Every domain decision — what a betslip is, how to resolve the
score conflict, what counts as sharp — was mine, argued out in the transcript.

---

## The prompts that changed the project

Chronological. Each one is what I actually typed, with a note on what it caused.

### 1. Framing the problem

> I'm a candidate in a Sporting Risk selection process. The CEO sent me two
> independent take-homes and I want to build both in this repo. […] Task 1 —
> Betflow Analysis. Betslip data from a client (RetaBet, Spain + Peru), Mar–Jun
> 2026, football only. Columns: Sport, Competition, MatchId, MATCH, Event date
> (utc), Market, BetType, Player, Option, Betslip date (utc), Uid, Management
> unit, Price, TURNOVER, GGR, Net Revenue, Currency Code. Header on row 5, data
> from row 6, columns B:R, sheet Sample1. […] He explicitly said: *"don't limit
> yourself to that. Go as bold and far reached as you can."* […] Task 2 — Two-feed
> reconciliation (Python preferred, 3–4h cap).

The full brief, including the file layout quirks, given once and up front rather
than discovered piecemeal.

### 2. Scope: is this analysis, or is it a product?

> A question: is Task 1 more about analysis? Or does it make sense to build
> charts too?

> Then I want a small frontend, to show these charts better. A betting-analytics
> frontend using impeccable + the taste skill.

> Yes, and it can have a notebook too. To show the depth in data + engineering.

This is where Task 1 stopped being a report and became two deliverables — a
pipeline and a surface.

### 3. The language constraint

> No, nothing can be in Portuguese in this project. **Everything** has to be in
> English, it's a company abroad.

Corrective. Early output had Portuguese in comments and chart labels. From here
on, every artifact in the repository is English; only the conversation stayed
Portuguese.

### 4. Stop building pieces, agree on the whole

> I don't think it makes sense to start building things in isolation. My point
> now is: let's use /grill-with-docs and do a general interview about what we
> want from the project. What do you think about starting with Task 1, which
> takes longer? Frontend, notebook, etc. Do it, and then move to Task 2?

The pivot to interview-first. Directly responsible for `CONTEXT.md` and the six
ADRs in `docs/adr/` — the domain language and the contested decisions were
settled before implementation, not documented after it.

### 5. Planning as a separate step

> Spawn an agent with the Fable model and plan first.

Repeated before each subsystem: the pipeline modules (`betflow.py`, `sharp.py`,
`pipeline.py`), the dashboard, each redesign, and the reconciliation service.

### 6. Visual identity from their brand, not invented

> https://sportingrisk.com/…/LOGO-Sport.svg — see if we can follow their logo's
> identity.

Led to the brand extraction documented in `DESIGN.md`: their surface colour and
accent taken from their own stylesheet, and — the part worth reading — their
Bootstrap defaults deliberately *rejected* as framework leftovers rather than
identity.

### 7. First design rejection

> impeccable + the taste skill made this ugly thing?? It's horrible. Spawn an
> agent with Fable to improve the design. Use icons, shadcn, things that show
> it's a professional dashboard. Use different fonts — one for figures, one for
> headings and one for descriptions, look for references. Albert Sans for text
> is a good option.

The three-role type system in `DESIGN.md` comes from this message.

### 8. Second design rejection — the one that mattered

*(sent with two screenshots)*

> Still horrendous. impeccable suggested this? What a horrible thing. **This is
> not a report. It's a product, an operational one. Imagine this Excel is going
> to be an API that a team follows and uses every day operationally.**

The most important instruction in the project. It moved the dashboard from
"readable document with charts" to a dense monitoring cockpit: active alerts on
top, prose stripped out, every figure traceable. Two follow-up agents were
spawned purely to remove explanatory prose from the sections.

### 9. Rejecting a bad answer to a real problem

> Turnover 1,116,431.73 EUR · 375,804.75 PEN · 596.18 USD — how hard is it to
> have a select for each? What a ridiculous thing.

Three currencies were being shown side by side because ADR-0001 forbids
converting between them. The constraint was right; the interface was lazy. Became
the global currency selector.

### 10. History as reviewable work

> I created the repo on GitHub. […] Separate each part into PRs / branches, with
> atomic commits, not co-authored with Claude, conventional commits, each PR with
> a description of what was done. Can you do that from the development history?

47 commits across 14 pull requests. To be explicit about the "not co-authored"
instruction: the work was AI-assisted throughout and this document exists to say
so plainly — I chose to keep the trailer off the commits and put the disclosure
here instead, where it can actually be read.

### 11. Checking the work against the brief

> Does Task 1 meet all the requirements? *(pasted the CEO's full requirement list)*

A deliberate audit pass, requirement by requirement, before considering it done.

### 12. Reframing the deliverable

> I'd drop the "task" naming, leave two folders: betflow/ reconciliation/. Make
> the main repo README detailed and complete, and in each one the details of how
> to run it. […] Present it as an actual product, drop the task idea.

Why the repository reads as two products rather than two exercises.

---

## What the AI did, and what it didn't

Being precise about this, since it's the actual question:

**It wrote nearly all the code.** The Python pipeline, the React cockpit, the
reconciliation service, the tests. I reviewed it, ran it, and rejected it when it
was wrong.

**It found things I did not ask it to find.** The clearest example is in Task 2:
while planning, it noticed that both feeds' own per-player goal tallies sum to
2–1, which means beta's `result: 2-2` contradicts beta's own lineup data. That
turned the score conflict from an arbitrary "prefer provider X" rule into an
evidence-based resolution. That is in `reconciliation/SUBMISSION.md` because it
was a genuine discovery, and I'm naming its origin here rather than quietly
taking credit for it.

**The decisions were argued, not accepted.** Every ADR in `docs/adr/` exists
because a question got contested in the transcript — whether to convert
currencies (no), what identifies a betslip (Uid + timestamp, split by BetType),
whether to rank sharp customers or test for sharp behaviour (test, with
false-discovery-rate control, because a leaderboard invents precision it doesn't
have). Those are the calls that shaped the analysis, and they are the ones I'd
defend in person.

**The taste was mine, applied by rejection.** The dashboard is on its third
architecture. The first two came back as competent, generic analytics pages, and
what got them rejected was knowing what a trading desk actually needs to look at
at 11pm — which no tool supplied.

The honest summary: the AI made me faster and caught things I would have missed.
It did not decide what mattered.
