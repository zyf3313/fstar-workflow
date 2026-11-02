# Technical design profiles

Source reference: `zyf3313/fstar-trellis-ext`, commit `674bea37cf2f6f25cd20dab93e1a54ae1f13ce66`, `spec/templates/technical-design-profiles.zh-CN.md`. The persisted research contains the verified structure but not exact source text, so this host-neutral card preserves attribution and the approved adaptation without claiming a verbatim copy.

Combine only applicable profiles: Web/API, frontend/mobile/desktop, CLI/SDK/library, data/batch/async, and infrastructure/configuration. For each, document the concrete contract, processing, failures, compatibility, and actual state owner. Use Mermaid by default; other diagram tools require editable source, exported image, identifier, and generation method.

Chapter references use the adapted design: chapter 7 is Impact Scope only (project module, affected function/scope, change and impact; no mandatory code details), chapter 8 is Configuration and Dictionaries, chapter 9 is Appendix, Review, and Version. Testing remains in PRD acceptance, per-function design, plan validation, and actual check evidence; do not create a test-cases document or approval prerequisite.
