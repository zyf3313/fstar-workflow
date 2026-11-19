---
name: fstar-help
description: "Explain only installed entries and observed configuration. 只读解释实际安装能力与配置。"
---

# Help

## Do NOT use when
- The user asks to change anything: Help is read-only; route writes to their owning skills.
- The question is about what to do next in a task: that is routing, not installation state.

Run `fstar --json doctor` and use its `entries` report, which verifies the installer entry index against actual configuration on disk. Use the current installation's root options when applicable. Explain active and missing entries and diagnostics; an absent index is not proof that entries are installed. Distinguish estimated listing size from observed host behavior. Doctor is read-only; do not initialize a project, enable an extension, alter configuration, or claim host integration was tested.
