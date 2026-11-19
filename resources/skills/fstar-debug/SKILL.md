---
name: fstar-debug
description: "Preserve failures, find root cause, bound fixes, and recheck. 保留失败证据、定位根因并复查。"
---

# Debug

## Do NOT use when
- This is a first-time routine failure inside the current check: stay in `fstar-check` repair.
- The failure is a requirement or scope question: return to `fstar-clarify`.

Preserve actual failure output and the input/delivery baseline. Classify the root cause before changing scope. Bound a fix and its required recheck; do not erase evidence or weaken expectations. Native dispatch may retry once after a dispatch failure with the prior reason; a second failure or no progress stops dispatch and enters this flow. Report unresolved limitations instead of claiming recovery.
