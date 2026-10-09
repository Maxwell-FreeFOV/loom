---
type: wiki
title: v1 scope
created: 2026-10-01
updated: 2026-10-01
tags: [demo]
sources: ["[[requirements]]", "[[approach-options-card]]"]
---

# v1 scope

<!-- Demo data for Loom's documentation example; not a real project. -->

> One sentence: what the first version of the reading-excerpt tool does — and deliberately does not do.

## Key points
- v1 = save excerpts locally (as Markdown) + search them locally. (source: [[DR-2026-001_v1-local-excerpts]])
- Sharing and multi-device sync are out of scope for v1, because they require a server and accounts, which the constraints forbid. (source: [[requirements]])

## Details

The tool stores one excerpt per note with its origin (page, section, link). Search is plain-text over the folder.

## Disputes and uncertainties
- Whether plain-text search stays adequate at a few hundred excerpts is untested; revisit at the review date of [[DR-2026-001_v1-local-excerpts]].

## Related
- [[DR-2026-001_v1-local-excerpts]]
- [[approach-options-card]]

## Change log
- 2026-10-01: created
