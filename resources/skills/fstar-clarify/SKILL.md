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

Model the discussion as a **design tree**: every decision branches into the decisions that hang off it. The **frontier** is every decision whose prerequisites are already settled — the questions you can ask now without guessing at answers you have not heard.

Work the tree in rounds:

1. Find the facts first, never the user: inspect specs, code, tests, and configuration for every frontier question. Never ask the user for something you can look up yourself. Before forming a question, also check what is already settled: the user's rules, project knowledge, and the rejected-proposals ledger (`.fstar/knowledge/references/rejected.md`) — a question whose answer is already recorded there is not asked again; cite the recorded answer instead. When a fact needs bounded research and the multi-agent `research` member is granted, dispatch fstar-research; do not block the rest of the frontier on it — only questions downstream of that fact wait.
2. Ask the whole frontier in one round: number each question, give your recommended answer, and word the question so "yes" accepts the recommendation. Wait for the user's answers before the next round. A question whose answer depends on another question still open in this round belongs to a later round, not this one.
3. Settled decisions push the frontier outward. Recompute the frontier from the answers and ask the next round. A round ends with nothing silently assumed: every branch is either settled, asked, or marked confirm-as-you-go with its confirmation moment.

Not every open question must be settled before moving (C-16): a question whose answer affects the current scope is blocking; a question that can be settled later without rework is marked "可边做边确认" (confirm-as-you-go) with its confirmation moment, and work proceeds. Judge the scope of each open question — this conversation, one deliverable, one step, the whole goal, or a lasting preference — before deciding. Never treat a recommendation or an inference as the user's confirmation.

At clarification close: form the acceptance criteria (criteria.md) from the goal and the user's own words — each criterion carries the user quote or confirmed conclusion it rests on — and ask once about delivery preference (where deliverables live and in what form, C-09); record the answer as a preference clue and reuse it afterwards instead of asking again.

Maintain clarify.md yourself using the task template, updating it after each round: the decision tree with its current frontier, open questions each carrying a recommended answer (and, for non-blocking ones, the confirmation moment), confirmed conclusions with the user's exact quote, and superseded conclusions with the reason. Distinguish verified facts, proposals, confirmed conclusions, and open questions; do not copy whole chat transcripts. Put multi-source comparisons, protocols, or probes in research/ using the research template. Pass only explicit conclusions to plan and execute.
