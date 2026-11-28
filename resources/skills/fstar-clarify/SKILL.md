---
name: fstar-clarify
description: "Explore evidence and decision dependencies. 依据证据和决策依赖澄清。"
---

# Clarify

## Do NOT use when
- The goal and its acceptance conditions are already settled and no open decision depends on this discussion: go to `fstar-plan` (only when the item needs one) or `fstar-execute`.
- The user asks to resume interrupted work: use `fstar-continue`.
- The user asks to store an existing planning document: use `fstar-plan` (planning-document storage is a plan duty).

Use when the goal still carries unresolved decisions that affect what gets built or accepted. The interview protocol below is a structural adaptation of the `grilling` skill in mattpocock/skills (MIT); this is not a verbatim copy.

## The clarification loop after task creation (A-007)

Task creation is an early action, not the end of exploration. After the task is created (by the coordinator or a dispatched steward), the conversation MUST return to requirement discussion: answer the user's opinion-seeking first (when their message asks "what do you think / which option", respond with analysis before anything else), supplement the options analysis, and keep the round-trip going until requirements are clarified. While clarification is incomplete: generate no planning document, advance no phase, and do not ask about next steps — continuing the exploration takes precedence over every advancing action.

Model the discussion as a **design tree**: every decision branches into the decisions that hang off it. The **frontier** is every decision whose prerequisites are already settled — the questions you can ask now without guessing at answers you have not heard.

Work the tree in rounds:

1. Find the facts first, never the user: inspect specs, code, tests, and configuration for every frontier question. Never ask the user for something you can look up yourself. Before forming a question, also check what is already settled: the user's rules, project knowledge, and the rejected-proposals ledger (`.fstar/knowledge/references/rejected.md`) — a question whose answer is already recorded there is not asked again; cite the recorded answer instead. When a fact needs bounded research and the multi-agent `research` member is granted, dispatch fstar-research; do not block the rest of the frontier on it — only questions downstream of that fact wait.
2. Ask the whole frontier in one round: number each question, give your recommended answer, and word the question so "yes" accepts the recommendation. Wait for the user's answers before the next round. A question whose answer depends on another question still open in this round belongs to a later round, not this one.
3. Settled decisions push the frontier outward. Recompute the frontier from the answers and ask the next round. A round ends with nothing silently assumed: every branch is either settled, asked, or marked confirm-as-you-go with its confirmation moment.

## Grill mode (A-011/A-012, adversarial clarification)

The exploration is lead-taking, not answer-waiting. Four rules:

1. **Pose the open questions each round (主动出题)**: before each round closes, list "potential requirements, risks, and boundary gaps that were discovered but not yet discussed" on your own — never wait for the user to ask "what problems remain".
2. **Grill every new claim (主动 grill)**: run each of the user's new claims through the challenge checklist by default — implicit assumptions, failure criteria ("how would we know this failed?"), boundary conditions, undeclared expectations. A point you cannot explain is marked 待确认 (to-confirm) and is not carried into plan; it never enters planning silently.
3. **Position first (立场前置)**: when options disagree, give your recommendation and its reasoning before listing the options — never throw the whole decision tree at the user.
4. **Closing self-check (收口自查)**: "no more" from the user is not the endpoint — it triggers a completeness self-check (sources, boundaries, criteria, conflicts). Findings continue the discussion; no findings earns an explicit "we have no open items on our side, awaiting your decision".

Not every open question must be settled before moving (C-16): a question whose answer affects the current scope is blocking; a question that can be settled later without rework is marked "可边做边确认" (confirm-as-you-go) with its confirmation moment, and work proceeds. Judge the scope of each open question — this conversation, one deliverable, one step, the whole goal, or a lasting preference — before deciding. Never treat a recommendation or an inference as the user's confirmation.

At clarification close: form the acceptance criteria (criteria.md) from the goal and the user's own words — each criterion carries the user quote or confirmed conclusion it rests on, and declares whether it needs a design document (a `design-required` marker in criteria.md gates `fstar start` for design-needing tasks) — and ask once about delivery preference (where deliverables live and in what form, C-09); record the answer as a preference clue and reuse it afterwards instead of asking again.

Maintain clarify.md through a dispatched worker (fstar-steward for first-draft creation, fstar-editor for later entry updates) so the main conversation stays free of file operations (A-008); when the host provides no sub-agent facility, the main Agent maintains it directly for that case. The file uses the task template, updated after each round: the decision tree with its current frontier, open questions each carrying a recommended answer (and, for non-blocking ones, the confirmation moment), confirmed conclusions with the user's exact quote, and superseded conclusions with the reason. Distinguish verified facts, proposals, confirmed conclusions, and open questions; do not copy whole chat transcripts. Put multi-source comparisons, protocols, or probes in research/ using the research template. Pass only explicit conclusions to plan and execute.
