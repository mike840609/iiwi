"""Prompt contract for evidence-backed outcome synthesis."""

_OUTCOME_PROMPT = """Synthesize evidence-backed engineering outcomes from the attached
redacted session evidence. Return JSON only; do not wrap it in prose.

Aim for 3–5 ranked outcomes when the evidence supports that many. You may emit
more candidates when they are independently meaningful. Each response must use
exactly this shape:

{
  "outcomes": [
    {
      "title": "concise outcome title",
      "status": "completed | in_progress",
      "impact": "supported impact, or empty string",
      "source_session_ids": ["known session id"],
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

Only use source_session_ids present in the attached evidence; do not use unknown session ids.
Do not emit repository ids, files, commits, activity ids, or any
other evidence references: Iiwi reconstructs those from known evidence.

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
