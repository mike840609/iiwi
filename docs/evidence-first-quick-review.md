# Evidence-first Quick Review

Quick Review turns selected coding sessions into a short list of traceable
outcomes before Iiwi writes a report. The target is a 30–60 seconds review:
remove noise, correct wording, check evidence, and preview the exact output.

## Start the review

Run `iiwi`, choose **Generate Report**, and open **Review sessions**. Select the
sessions that belong in the update, then press `g` to generate outcome candidates.
Iiwi synthesizes only that selection.

Up to five outcomes are selected initially. All additional results remain under
**More candidates**. Open that section, exclude a primary outcome with `Space`,
and include a stronger candidate with `Space` to replace it. If evidence
extraction fails for a session while other synthesis succeeds, that work remains
under **Ungrouped candidates** for an explicit reviewer decision.

## Review keys

```text
Space Include/exclude │ e Edit │ J/K Reorder │ v Evidence │ s Split │ a Add
p Preview │ g Generate │ b Back
```

| Key | Responsibility |
|---|---|
| `Space` | Include or exclude the focused outcome. |
| `e Edit` | Edit title, status, and Impact without changing its evidence identity. Leave Impact empty when the evidence does not support one. |
| `J/K` | Move the focused outcome down or up in reviewed order. Lowercase `j/k` only moves focus. |
| `v Evidence` | Expand or collapse repository and session references. |
| `s Split` | Split a synthesized cross-repository outcome into its existing source groups. |
| `a Add` | Create a User-added outcome. It is labeled **User added** in the report and carries no synthesized evidence. |
| `p Preview` | Render the exact in-memory draft without writing the output file. |
| `g Generate` | Write the reviewed draft using the selected Report type and Detail. |
| `b Back` | Return to the previous screen. Returning from Preview preserves every edit. |

Blockers and Next week are optional rows. Enter on either row to add or replace
its text; an empty answer leaves that section out of the report.

## Report type and Detail

Report type chooses the audience and heading. Detail chooses how much supporting
material is rendered. They are separate responsibilities:

| Setting | Owns | Default relationship |
|---|---|---|
| **Manager** | A concise weekly-update heading and audience. | Defaults to **Brief** until Detail is explicitly changed. |
| **Engineering** | An engineering-worklog heading and audience. | Defaults to **Full** until Detail is explicitly changed. |
| **Brief** | Outcomes, In Progress, Blockers, Next week, and warnings. | Omits the Evidence and Usage sections. |
| **Full** | The same reviewed outcome prose. | Also includes traceable Evidence and available Usage. |

Enter on the Report row to switch Manager or Engineering. An explicit Detail
choice remains in force when the Report type changes. The persisted default is
`report.quick_review_report_type`; see the [configuration guide](configuration.md).

## Preview, generation, and recovery

Use `p Preview` before sharing. Preview and recoverable errors preserve the same
in-memory draft, including include/exclude decisions, edits, order, User-added
outcomes, Blockers, and Next week. Press `b` to return and continue reviewing.
Use `g Generate` only when the preview matches the intended Report type and Detail.

If a preview fails, choose **Retry** or **Back to Quick Review**. If outcome
synthesis fails completely, the recovery screen offers **Retry**, **Use
session-based report**, and **Back**. The session-based report is an explicit
fallback and is labeled with a warning; Iiwi never silently presents it as a
reviewed outcome report. Partial synthesis continues with successful outcomes
and exposes failures as **Ungrouped candidates**.

## Version-one exclusions

- **No persistent drafts.** The draft exists only for the current interactive run.
- **No manual merge.** Reviewers can split a synthesized merge but cannot create a
  new merged outcome by hand.
- There is no separate outcome editor outside the terminal Quick Review flow.

