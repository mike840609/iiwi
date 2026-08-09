# Architecture

<!-- Rendered image, not a mermaid block: the GitHub mobile app and PyPI show
     mermaid source as plain text. Edit docs/assets/architecture.mmd and follow
     the regenerate command at the top of that file. -->

![Architecture: CLI reads one of three session sources, scans and resolves repositories, then extracts, redacts, summarizes, and writes the report](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/architecture.svg)

Iiwi loads only the sessions that overlap the requested period, groups them by
repository, redacts and summarizes the evidence, then writes the Markdown report
atomically with owner-only permissions.

The diagram is generated. Edit
[`docs/assets/architecture.mmd`](https://github.com/mike840609/iiwi/blob/main/docs/assets/architecture.mmd)
and regenerate with `docs/assets/render-architecture.sh`; never hand-edit the SVG.
