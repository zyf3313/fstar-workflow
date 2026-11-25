# Verified reproduction baseline

Source note: uTools note/1795522260367, “fstar 0.11.1 缺陷复现手册”, read 2026-11-24. Tests used installed fstar-workflow@0.11.1, two isolated user-directory projects, dedicated user/runtime/host roots. Production projects and global installation were not changed by reproduction.

Raw evidence directory: /var/folders/jc/_t2cms2s37g2qgn6rst44x000000gn/T/fstar-0111-verify-xo7ihp0n.

## Observed before implementation
- B-11: CLI add-deliverable a.txt created {'a.txt': {}}. EvidenceService.snapshot(... items=['R1']) then raised mapping_missing. Independently constructed check scope for R1 failed invalid_check_scope. An empty path entry is not the completed evidence fix.
- B-07: identical dispatch payload registration called four times produced four dispatch_registered events for the same dispatch_id.
- stdin: --payload - returned invalid_json_file with path '-' and ENOENT (exit 2).
- Cross-project lookup: task only-in-repo2 was created in repo2. repo1 state show returned task_not_found, no candidate location.
- Host symlink: native installer-owned fstar-init skill directory replaced with an external directory link. Identical file contents: dry-run exit 0, actual update exit 2 unsafe_path for both ordinary and native-only mode. Different external file contents: default keep policy exit 0 with keep_modified. External target was not written by updater.

## Boundaries retained
- General-purpose worker hook emitting nothing is documented design, not a bug to repair here.
- Ordinary production edit doc-change hook emitting nothing is outside its task-document scope, not a bug to repair here.
- stderr status line exists, but shell output alone does not prove actual host UI visibility. No new UI claims or hook output changes in this task.
- No fstar status overview command in this batch.

## Verification lessons for this task
- End-to-end acceptance must reach downstream EvidenceService and task transitions, not just inspect intermediate JSON keys.
- Compare update preview with actual apply; identical content can still fail during path validation.
- Retain one dispatch identity per native worker execution; a registration is not an executed worker.
- Use canonical snapshot helpers; never random digests or copied run IDs to force acceptance.
