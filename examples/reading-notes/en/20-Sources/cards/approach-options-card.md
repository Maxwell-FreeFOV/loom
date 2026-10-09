---
type: source
title: Candidate approaches for the excerpt tool
created: 2026-10-01
updated: 2026-10-01
tags: [demo]
origin: "[[approach-options]]"
url: 
author: myself
published: 2026-10-01
credibility: high
---

# Candidate approaches for the excerpt tool

<!-- Demo data for Loom's documentation example; not a real project. -->

## One-sentence summary

Three ways to build the excerpt tool — plain Markdown files, a local SQLite CLI, or a web app — trading structure and sharing against infrastructure and file ownership.

## Key points
- Option A (Markdown + local search) has zero infrastructure and keeps everything as plain files.
- Option B (SQLite CLI) adds structured queries but needs a schema and import step.
- Option C (web app) is the only one with sync and sharing, at the cost of a server and accounts.

## Relevance to this project
- Direct input to [[DR-2026-001_v1-local-excerpts]]; see [[v1-scope]] for what v1 actually includes.

## Questions and things to verify
- How painful are structured queries in option A really, once there are a few hundred excerpts?
