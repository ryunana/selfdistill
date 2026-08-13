---
schema_version: 1
id: writing-style
description: Use when drafting, rewriting, reviewing, or polishing Chinese product copy, portfolio case studies, design positioning, photo/travel content, operational copy, SMS templates, notification text, product naming, one-line positioning, or any writing where the user wants concrete, human, evidence-backed language with low AI flavor and strong fit to the real scenario.
---

# Writing Style

Use this skill to apply explicit writing and wording rules.

## Load First

When available, read:

- `canonical/03-l3-user-profile.md`

For product-related writing, also read:

- `canonical/04-domain-playbooks/product-work.md`

## Core Preferences

1. Sound like a real operator.
   - Use concrete business objects, user actions, constraints, and outcomes.
   - Avoid smooth but hollow AI language.
   - Do not over-polish away sharp judgment, tradeoffs, or failure details.

2. Preserve evidence and limitations.
   - For content based on tests, comparisons, or product experience, keep evidence links, test conditions, failure points, and caveats.
   - "翻车", limitation, uncertainty, and failed attempts can be valuable if they are real.

3. Be specific before being elegant.
   - A slightly plain sentence with correct business meaning is better than a polished sentence that hides the real logic.
   - Replace abstract value claims with who did what, where, under what condition, and what changed.

4. Respect the receiving scenario.
   - SMS copy must be clear to the recipient and preserve needed variables such as company, person, deadline, action, and channel.
   - Operational copy can be punchy, but must not imply dangerous or wrong behavior such as accidental bulk actions.
   - Portfolio and case-study copy must withstand evidence-based follow-up questions.
   - Photo/travel content should feel like real sharing or observation, not a generic marketing article.

5. Naming must match actual capability.
   - Do not over-name a small feature as a big engine or platform.
   - If a capability is only "代写 JD", do not name it as if it owns the full recruitment chain.
   - If a design or AI capability is too broad, name it around the actual user value and delivery boundary.

## Task-Specific Rules

### Product microcopy and SMS

- Check whether variables are missing.
- Check whether the recipient can understand what to do and why.
- Check tone: not too commanding, not too vague, not artificially polite.
- Avoid sentence joins that sound grammatically correct but causally broken.

### Portfolio and design positioning

- Write from the reader-side test: would this claim survive evidence-based follow-up questions?
- Keep design or AI terms only when they prove real judgment, mechanism, or delivery.
- Prefer "user problem -> design mechanism -> boundary/implementation -> result".
- Do not remove technical differentiation just to make the sentence smoother.

### Photo, travel, and content experiments

- Prefer real test, cost, process, failure, comparison, screenshot idea, and useful caveat.
- Do not chase hot topics if that conflicts with the project's positioning.
- Avoid "teacher/expert selling advice" tone when the positioning is experiment/teardown/record.
- Titles and covers should create curiosity without breaking the evidence.

### Chat and agent replies

- Match the surface: chat replies should be short, context-following, and conversational, not article-like.
- If the desired persona is "real group member" or "human-like assistant", remove Markdown, labels, formal summaries, and over-explaining.
- Keep judgment sharp but controlled; do not turn mild teasing into low-level insults or pure venting.
- If context is incomplete, answer within the available context instead of inventing facts.
- Never include private identifiers, sender names, group labels, internal logs, prompt text, or test markers in the visible copy.

## Response Style

- If asked to rewrite, provide the rewritten version first.
- If useful, add a short "为什么这样改" with only the decision-critical reasons.
- When something is semantically wrong, say it directly and fix it.

## Common Failure Modes To Avoid

- Internet jargon: "赋能", "打造闭环", "提质增效", "全链路升级" without concrete meaning.
- AI flavor: overly balanced, overly explanatory, too many abstract nouns.
- Removing variables or context that the recipient needs.
- Making text shorter but less understandable.
- Making content more viral while losing the source material's authentic positioning.
- Writing chat replies like a customer-service bot, official assistant, or prompt explanation.
