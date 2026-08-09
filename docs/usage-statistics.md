# Usage statistics

With `--harness opencode`, each report includes a usage section built from `opencode
stats`, covering models, tokens, and tools. OpenCode reports usage only for a period that
ends now. The period shown in the report therefore starts when the report period starts
and runs to the time the report is created. It covers the report period but is wider than
it. If `opencode stats` is not available, Iiwi leaves the section out and adds a
warning to the report.

With `--harness claude-code` or `--harness codex`, the usage section is built from token
counters recorded in the sessions themselves, so it covers the report period instead of a
window that ends when the report is created; the "wider than the period" caveat above does
not apply. It counts every model turn in the period, including turns that produced only
internal reasoning, whose tokens are carried by the neighbouring recorded activity. That
last part is also its one imprecision: a turn sitting exactly on the period boundary can be
counted on the other side of it. For Codex specifically, the count itself is what Codex
reports for each API request's full input, not a count of distinct tokens.
