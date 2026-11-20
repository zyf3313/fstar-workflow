---
name: fstar-help
description: "Explain only installed entries and observed configuration. 只读解释实际安装能力与配置。"
---

# Help

## Do NOT use when
- The user asks to change anything: Help is read-only; route writes to their owning skills.
- The question is about what to do next in a task: that is routing, not installation state.

Run `fstar --json doctor` and use its `entries` report, which verifies the installer entry index against actual configuration on disk. Use the current installation's root options when applicable. Explain active and missing entries and diagnostics; an absent index is not proof that entries are installed. Distinguish estimated listing size from observed host behavior. Doctor is read-only; do not initialize a project, enable an extension, alter configuration, or claim host integration was tested.


## Shared global resources

Workflow resources live in the shared global entry (`~/.claude` for skills, agent cards, and hooks) and are updated globally; a project keeps only its tasks, specs, and identity. When the user asks where resources are installed, what a project still carries, or whether an update took effect, answer from the observed state: `fstar --json doctor` for the entry index and resource health, and `fstar --json resource-inspect` for the read-only comparison of one project's legacy resources against the global target. The comparison writes nothing and records nothing; showing the migration question is the explicit `fstar resource-remind` operation, and the user's approval is the explicit `fstar resource-migrate --confirmation FILE`. Explain a migration offer as an offer, not as a completed change: only the user's explicit approval moves anything, and files the installer does not own — or that the user modified — are kept and reported. A deferral (`fstar resource-defer`) applies to that project and target version only; a new global version makes the project eligible again. If the global entry is incomplete or modified, report the diagnosis and the recovery step instead of claiming the update succeeded. Magpie integration is optional and skills-only: only the public hand-over command is used, Magpie-private files are never edited, and hook/agent cards stay in the tool-native global entry.