<!-- Demo data for Loom's documentation example; not a real project. -->

# Candidate approaches for the excerpt tool

A. **Plain Markdown files + local search.** Each excerpt is a note; search with ripgrep or the editor. Zero infrastructure, files stay mine. Weak on structured queries (e.g. "all excerpts from one book with tag X").

B. **Local SQLite + small CLI.** Structured fields (source, page, tags) and fast filtered queries. Still fully local. Costs a real schema and some import friction.

C. **Web app with sync and sharing.** Solves multi-device and lets me share collections. Needs a server, accounts, and ongoing maintenance — and my notes stop being just files.
