"""Prompt contract for evidence-backed outcome synthesis."""

_OUTCOME_PROMPT = """Synthesize evidence-backed work outcomes from the attached
redacted session index. Return JSON only; do not wrap it in prose.

The attachment is a compact index of sessions. Each entry carries at most
source_id, repository_id, title, branch, goal, and outcome: goal is the
session's first stated goal, outcome is one outcome recorded in it, and both
arrive in full. Empty fields are omitted, so an entry may carry nothing beyond
source_id and repository_id. Group these sessions by the work they describe.

Aim for 3–5 ranked outcomes when the evidence supports that many. You may emit
more candidates when they are independently meaningful. Each response must use
exactly this shape:

{
  "outcomes": [
    {
      "title": "concise outcome title",
      "status": "completed | in_progress",
      "impact": "supported impact, or empty string",
      "source_ids": ["known source id"],
      "confidence": "high | medium | low",
      "linkage_signals": [
        {
          "kind": "one allowed linkage kind",
          "value": "observed linkage value"
        }
      ]
    }
  ]
}

Only use source_ids present in the attached index; do not use unknown source ids.
Do not emit repository ids, files, commits, activity ids, or any
other evidence references: Iiwi reconstructs those from the full local evidence,
which is why the index does not carry them. Never invent a file, commit, or
activity id to fill the gap.

Allowed linkage kinds are shared_work_id, branch_or_issue, direct_reference,
similar_wording, and timestamp_proximity. Merge sessions from different
repositories only with high confidence and either
one shared_work_id signal, or both distinct branch_or_issue and direct_reference
signals. Similar wording or timestamp proximity alone never supports a
cross-repository merge. When Impact is unsupported by the supplied evidence,
Impact must be "". Do not invent work, status, impact, or linkage evidence.
"""


def build_outcome_prompt() -> str:
    """Return the fixed outcome-synthesis instruction contract."""

    return _OUTCOME_PROMPT
