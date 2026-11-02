---
name: fstar-init
description: "Initialize from verified project facts; preserve authority. 基于事实初始化，保留权威资料。"
---

# Init

Explore the whole project and existing authoritative material before asking for missing background. Collect a JSON object with `project_summary` (string), `topics` (objects with `id`, `title`, `applies_to`, `read_when`, `path`), and optional `authority_refs` and `knowledge_refs` (objects with `title`, `path`). All paths refer to existing project files. Pass the file to `fstar init <project-path> --context <json-file>` and verify navigation. The command also attempts a read-only initial tool proposal scan without requiring extension grants; binding changes require separate user confirmation. If it reports `TOOL_SCAN_FAILED`, initialization succeeded but the scan failed. Reference existing authority instead of inventing guidance. `INDEX_PRESERVED` means new context was not applied. Remove any temporary context file when finished.
