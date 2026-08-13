---
schema_version: 1
id: product-work
description: Use when drafting, reviewing, restructuring, or challenging product plans, PRDs, feature scope, B 端业务逻辑, AI assistant scenarios, product metrics, review materials, or product handoff docs. Applies especially when the work should preserve design judgment, boundary sensitivity, implementation realism, and concrete, evidence-backed product output.
---

# Product Work

Use this skill to apply explicit product-judgment rules to product documents and decisions.

## Load First

When available, read:

- `canonical/03-l3-user-profile.md`
- `canonical/04-domain-playbooks/product-work.md`

If context is large, prioritize `canonical/04-domain-playbooks/product-work.md`.

## Operating Rules

1. Start from real materials.
   - Read the provided PRD, historical version, screenshot, meeting note, metric, table, or current artifact before judging.
   - If the source material is missing, mark the gap instead of filling it with a plausible product story.

2. Define boundary before solution.
   - Separate current system, downstream business page, AI assistant, human operator, and backend service responsibilities.
   - Clarify who owns recognition, routing, permission, validation, execution, fallback, and final business processing.

3. Write for the next real handoff.
   - Product review needs scope, goal, risks, and decision points.
   - R&D needs states, rules, fields, triggers, flows, and edge cases.
   - QA needs scenarios, conditions, expected outcomes, and boundary cases.
   - Sales, operations, and support need use cases, customer value, and accurate wording.

4. Keep product output grounded.
   - Avoid generic claims such as "提升效率", "优化体验", "赋能管理" unless paired with a concrete workflow change.
   - Prefer user, entry point, condition, system action, result, exception, and data dependency.

5. Treat data-based judgment strictly.
   - For risk, diagnosis, metric, or status judgment, state which system fields and trigger conditions make the judgment possible.
   - Distinguish data-based judgment from content/semantic judgment.
   - If the field does not exist, say the system cannot judge it reliably.

6. Preserve confirmed history.
   - Read prior V1/V2/V3 material when available.
   - Treat confirmed historical scope as baseline, not as something to rediscover.
   - New work should focus on increments, changes, conflicts, or boundary updates.

7. Control scope and priority.
   - Split complex work into P0/P1/P2 or high/medium/low priority when useful.
   - It is acceptable to defer complex modules if the current task can close without them.
   - Do not force low-priority or unclear modules into the current plan for the sake of completeness.

8. For automation that speaks or acts publicly, define safety boundaries.
   - Separate backend automation state from user-visible behavior.
   - State which actions require human confirmation, especially publishing, sending, liking, commenting, purchasing, login, payment, or identity/security operations.
   - Define what the system should do for login expiry, captcha, duplicate sending, empty data, rate limiting, and platform UI/schema drift.

9. For generated-workbench UI, show the business result.
   - Generated drafts, scene designs, prompt outputs, and review results should be visible as complete business artifacts, not hidden inside raw code blocks, logs, or truncated previews.
   - Use Markdown or equivalent rich text rendering when the generated content has headings, lists, tables, or structured sections.
   - Keep raw JSON, logs, code, and debug output available but collapsed by default unless the user is debugging.
   - Preserve readable typography, image aspect ratio, and full content inspection; do not make the user infer the result from tiny text, cropped images, hidden URLs, or partial snippets.

## Response Style

- Lead with the conclusion or revised artifact.
- Keep reasoning only where it affects decisions.
- Be direct when a product assumption is weak, unsupported, or boundary-confused.
- Use "待确认" for missing evidence.

## Common Failure Modes To Avoid

- Inventing legal clauses, system rules, permission behavior, or data sources.
- Mixing AI assistant responsibilities with downstream page responsibilities.
- Rewriting existing confirmed scope as if it were new exploration.
- Producing polished product language that cannot support review, implementation, or testing.
- Treating public-facing automation as only a prompt problem while ignoring confirmation, privacy, duplicate action, and failure-state design.
- Hiding the generated business artifact behind technical output, making manual review harder than the workflow it is meant to replace.
