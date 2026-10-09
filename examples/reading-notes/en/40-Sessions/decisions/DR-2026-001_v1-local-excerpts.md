---
type: decision
id: DR-2026-001
title: v1 supports local excerpts and search; sharing deferred
created: 2026-10-01
updated: 2026-10-01
status: decided
reversible: reversible
confidence: 70%
review_date: 2026-12-01
tags: [demo]
session: "[[2026-10-01_v1-scope]]"
outputs: []
commits: []
---

# v1 supports local excerpts and search; sharing deferred

<!-- Demo data for Loom's documentation example; not a real project. -->

## 1. The question to decide
With one person and no server budget, which approach from [[approach-options]] should v1 take?

## 2. Background and constraints
- Current situation: requirements collected in [[requirements]]; three candidate approaches compared in [[approach-options]].
- Time window: v1 should be usable within a few weekends.
- Hard constraints: no server, no accounts, files must stay plain text.
- Relation to the project goals: the brief's core value is finding excerpts later, not sharing them.

## 3. Options
| Option | Core benefit | Core cost | Worst case | Reversibility |
|---|---|---|---|---|
| A. Markdown + local search | zero infrastructure, files stay mine | weak structured queries | search gets unwieldy at scale | reversible |
| B. SQLite + CLI | structured, fast filtered queries | schema + import friction | the tool becomes the chore | reversible |
| C. Web app | sync and sharing | server, accounts, maintenance | project dies under its own weight | irreversible-ish |

## 4. Analysis
- Only C offers sharing, and C violates every hard constraint. Between A and B, A matches "own the files" best and can evolve into B later.

## 5. Strongest counterargument
- Plain-text search may turn out to be too weak once there are hundreds of excerpts, and retrofitting structure onto loose notes is painful.

## 6. Pre-mortem (suppose this decision turns out to be a failure after a while; what is the most likely cause)
- Excerpt volume grew fast, ad-hoc search stopped scaling, and migrating a pile of freeform notes into SQLite took longer than building B from the start would have.

## 7. Decision
- **Choice**: option A — v1 supports local excerpting and search; multi-person sharing is deferred.
- **Reasons** (no more than 3): zero infrastructure; files stay mine; A can grow into B without losing data.
- **Confidence**: 70%
- **What was given up**: multi-device sync and sharing in v1.

## 8. Next actions
- [ ] Write the minimal v1 feature list

## 9. Signals and stop-loss
- Signals that the decision was right: v1 in daily use within a few weekends; excerpts found in seconds.
- Signals that it should be reconsidered: regular frustration finding excerpts, or a real second user appears.

---
## Review (fill in when review_date is due)
- Actual outcome:
- What was right and what was wrong in the original judgment:
- Luck or decision quality:
- Principles learned (distill them into the relevant 30-Wiki pages):
