---
name: fstar-help
description: "Explain only installed entries and observed configuration. 只读解释实际安装能力与配置。"
---

# Help

Run `fstar --json doctor` and use its `entries` report, which verifies the installer entry index against actual configuration on disk. Use the current installation's root options when applicable. Explain active and missing entries and diagnostics; an absent index is not proof that entries are installed. Distinguish estimated listing size from observed host behavior. Doctor is read-only; do not initialize a project, enable an extension, alter configuration, or claim host integration was tested.
