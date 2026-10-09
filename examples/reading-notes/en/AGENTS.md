# reading-notes-demo

> A personal tool for saving and finding reading excerpts. Demo data for Loom's documentation.

<!-- loom:begin -->
## Loom Knowledge Base

This project is a Loom project knowledge base (the root contains a `.kb.json`). This block is maintained by Loom — do not edit it; project-specific conventions go outside the block.

- Before discussing or changing anything in this project, read `00-Hub/hot.md` first, then load the **loom** skill and read its `references/rules.md` (directory responsibilities, context loading order, knowledge ownership, writing conventions). If the "Loom common rules" were already injected at session start, there is no need to read them again.
- Archiving sessions, ingesting sources, linting, enabling modules, migrating, closing the project and similar operations are all done with the loom skill (`/loom <operation>` in Claude Code).
- `40-Sessions/raw/` (raw conversations) and `20-Sources/raw/` (raw sources) are append-only.
- When a substantive discussion ends, remind the user to archive it with loom (wrapup).
<!-- loom:end -->

## Project overview

- Starting point: two short notes — my requirements and three candidate approaches (demo data, invented for Loom's documentation).
- Current phase: defining the v1 feature list.
- See `10-Brief/project-brief.md`, `00-Hub/hot.md`, `00-Hub/roadmap.md`

## Project-specific conventions

- An "excerpt" is one saved passage together with where it came from (page, section, link).
