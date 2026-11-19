---
name: fstar-clarify
description: "Explore evidence and decision dependencies. 依据证据和决策依赖澄清。"
---

# Clarify

Use after planning-review authorization. The interview protocol below is a structural adaptation of the `grilling` skill in mattpocock/skills (MIT); this is not a verbatim copy.

Model the discussion as a **design tree**: every decision branches into the decisions that hang off it. The **frontier** is every decision whose prerequisites are already settled — the questions you can ask now without guessing at answers you have not heard.

Work the tree in rounds:

1. Find the facts first, never the user: inspect specs, code, tests, and configuration for every frontier question. Never ask the user for something you can look up yourself. When a fact needs bounded research and the multi-agent `research` member is granted, dispatch fstar-research; do not block the rest of the frontier on it — only questions downstream of that fact wait.
2. Ask the whole frontier in one round: number each question, give your recommended answer, and word the question so "yes" accepts the recommendation. Wait for the user's answers before the next round. A question whose answer depends on another question still open in this round belongs to a later round, not this one.
3. Settled decisions push the frontier outward. Recompute the frontier from the answers and ask the next round.

Stop when the frontier is empty: every branch of the design tree visited and nothing silently assumed. Do not pass a non-empty frontier to doc or plan; an unanswered frontier question is an unresolved requirement. The user's review of the planning documents is the shared-understanding confirmation — do not act on the outcome before it.

Maintain clarify.md yourself using the task template, updating it after each round: the decision tree with its current frontier, open questions each carrying a recommended answer, confirmed conclusions with the user's exact quote, and superseded conclusions with the reason. Distinguish verified facts, proposals, confirmed conclusions, and open questions; do not copy whole chat transcripts. Put multi-source comparisons, protocols, or probes in research/ using the research template. Pass only explicit conclusions to doc and plan.
