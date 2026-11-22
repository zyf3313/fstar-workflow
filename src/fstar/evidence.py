from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .models import DomainError
from .store import TaskStore, content_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _normal_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _extract_item(text: str, artifact_map: dict, item_id: str) -> Optional[str]:
    mapping = artifact_map.get(item_id)
    if not mapping:
        return None
    start, end = mapping.get("start_marker"), mapping.get("end_marker")
    if not start or not end or text.count(start) != 1 or text.count(end) != 1:
        raise DomainError("mapping_invalid", "Artifact mapping markers must each appear exactly once", {"item": item_id})
    before, rest = text.split(start, 1)
    body, after = rest.split(end, 1)
    if len(before) + len(body) + len(after) + len(start) + len(end) != len(text):
        raise DomainError("mapping_invalid", "Artifact mapping is ambiguous", {"item": item_id})
    return hashlib.sha256(body.encode()).hexdigest()


def validate_rework_scope(scope: Optional[dict]) -> dict:
    """Normalize and validate a rework scope object (S-4 K-1).

    ``None`` means the legacy full invalidation (every valid evidence goes
    stale). ``mode`` defaults to ``full``. A ``localized`` scope with all
    three lists empty is REJECTED (``invalid_rework_scope``) rather than
    silently degrading to full invalidation.
    """
    if scope is None:
        return {"mode": "full", "artifacts": [], "paths": [], "criteria_refs": []}
    if not isinstance(scope, dict):
        raise DomainError("invalid_rework_scope", "A rework scope must be an object")
    mode = scope.get("mode", "full")
    if mode not in {"full", "localized"}:
        raise DomainError("invalid_rework_scope", "A rework scope mode must be localized or full", {"mode": mode})
    normalized = {"mode": mode, "artifacts": [], "paths": [], "criteria_refs": []}
    for key in ("artifacts", "paths", "criteria_refs"):
        value = scope.get(key, [])
        if not isinstance(value, list) or not all(isinstance(entry, str) and entry.strip() for entry in value):
            raise DomainError("invalid_rework_scope", "Rework scope lists must be arrays of non-empty strings", {"field": key})
        normalized[key] = list(value)
    if mode == "localized" and not (normalized["artifacts"] or normalized["paths"] or normalized["criteria_refs"]):
        raise DomainError("invalid_rework_scope", "A localized rework scope requires at least one artifact, path, or criteria ref")
    return normalized


def _rework_scope_touches(evidence: dict, scope: dict) -> bool:
    """True when localized rework evidence intersects the scope.

    Intersection rules (S-4 K-1): validates artifact hit; validated item or
    dependency id hit a criteria ref; delivery/input/report path hit the
    scope paths or artifacts; a check's requirement ids hit a criteria ref.
    """
    artifacts = set(scope.get("artifacts", []))
    paths = set(scope.get("paths", [])) | artifacts
    criteria = set(scope.get("criteria_refs", []))
    for group in evidence.get("validates", []):
        if group.get("artifact") in artifacts:
            return True
        for entry in group.get("items", []):
            if entry.get("id") in criteria:
                return True
        for entry in group.get("dependencies", []):
            if entry.get("id") in criteria:
                return True
    for entry in (evidence.get("delivery") or {}).get("paths", []):
        if entry.get("path") in paths:
            return True
    for entry in evidence.get("input_files", []):
        if entry.get("path") in paths:
            return True
    if (evidence.get("report") or {}).get("path") in paths:
        return True
    if criteria and evidence.get("kind") == "check":
        for entry in evidence.get("items", []):
            if criteria.intersection(entry.get("requirement_ids", []) or []):
                return True
    return False


class EvidenceService:
    def __init__(self, store: TaskStore, *, clock: Optional[Callable[[], str]] = None):
        self.store = store
        self.clock = clock or utc_now

    def persist_artifact_map(self, ref: str, *, mapping: dict, source: dict) -> dict:
        """Persist content.py's readonly mapping output in core's canonical shape.

        Shape: {artifact: {item_id: {start_marker, end_marker, dependencies[]}}}.
        A top-level "mode": "file" key declares whole-file conservative mode for
        every artifact in the map: extraction is not item-scoped, so snapshots
        use granularity=file semantics (one hash per artifact) and any change
        to a mapped artifact invalidates dependent evidence.
        """
        normalized = {}
        for artifact, items in mapping.items():
            if artifact == "mode":
                if items != "file":
                    raise DomainError("mapping_invalid", "Unknown artifact map mode", {"mode": items})
                continue
            self.store.project_file(artifact)
            if not isinstance(items, dict):
                raise DomainError("mapping_invalid", "Artifact mapping items must be an object", {"artifact": artifact})
            normalized[artifact] = {}
            for item_id, spec in sorted(items.items()):
                if not isinstance(spec, dict) or not spec.get("start_marker") or not spec.get("end_marker"):
                    raise DomainError("mapping_invalid", "Each item requires literal start and end markers", {"artifact": artifact, "item": item_id})
                dependencies = sorted(set(spec.get("dependencies", [])))
                normalized[artifact][item_id] = {"start_marker": spec["start_marker"], "end_marker": spec["end_marker"], "dependencies": dependencies}
        if mapping.get("mode") == "file":
            normalized["mode"] = "file"
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "Artifact mapping cannot change on a dropped task", status=3)
            lease = task.get("lease")
            if lease and lease.get("expires_at", "") > self.clock():
                raise DomainError("lease_conflict", "Artifact mapping cannot change while a writer lease is active", {"holder": lease.get("holder")}, status=4)
            templates = task.setdefault("meta", {}).setdefault("templates", {})
            templates["artifact_map"] = normalized
            templates["artifact_map_sha256"] = content_hash(normalized)
            templates["artifact_map_source"] = source
            self.store.write(task_dir, task)
        return {"artifact_map": normalized, "sha256": content_hash(normalized)}

    def snapshot(self, ref: str, *, artifact: str, items: list) -> dict:
        task = self.store.read(ref)
        mappings = task.get("meta", {}).get("templates", {}).get("artifact_map", {})
        artifact_map = mappings.get(artifact, {})
        file_mode = mappings.get("mode") == "file"
        path = self.store.project_file(artifact)
        if not path.is_file():
            raise DomainError("artifact_missing", "Artifact does not exist", {"artifact": artifact})
        text = _normal_text(path)
        snapshots = []
        granularity = "item"
        if file_mode:
            # Whole-file conservative mode: no item-scoped extraction is
            # trusted, so every item snapshot binds the entire file content.
            granularity = "file"
            file_digest = hashlib.sha256(text.encode()).hexdigest()
            for item_id in items:
                snapshots.append({"id": item_id, "sha256": file_digest})
            return {"artifact": artifact, "items": snapshots, "dependencies": [], "granularity": granularity}
        for item_id in items:
            digest = _extract_item(text, artifact_map, item_id)
            if digest is None:
                if mappings.get("mode") == "file":
                    granularity = "file"
                    snapshots.append({"id": item_id, "sha256": hashlib.sha256(text.encode()).hexdigest()})
                    continue
                raise DomainError("mapping_missing", "No explicit artifact mapping exists", {"artifact": artifact, "item": item_id})
            snapshots.append({"id": item_id, "sha256": digest})
        # Bind the transitive dependency closure with content hashes so later
        # freshness checks can detect changes to any reachable item.
        dependencies = []
        seen = set()
        pending = [item["id"] for item in snapshots]
        while pending:
            current_id = pending.pop()
            if current_id in seen:
                continue
            seen.add(current_id)
            spec = artifact_map.get(current_id)
            if spec is None:
                raise DomainError("mapping_missing", "Dependency item has no mapping", {"artifact": artifact, "item": current_id})
            digest = _extract_item(text, artifact_map, current_id)
            if digest is None:
                raise DomainError("mapping_missing", "Dependency item has no mapping", {"artifact": artifact, "item": current_id})
            dependencies.append({"id": current_id, "sha256": digest})
            pending.extend(spec.get("dependencies", []))
        dependencies.sort(key=lambda entry: entry["id"])
        return {"artifact": artifact, "items": snapshots, "dependencies": dependencies, "granularity": granularity}

    def delivery_snapshot(self, paths: list) -> dict:
        entries = []
        for relative in sorted(set(paths)):
            path = self.store.project_file(relative)
            entries.append({"path": relative, "exists": path.is_file(), "sha256": file_digest(path) if path.is_file() else None})
        return {"paths": entries, "digest": content_hash(entries)}

    def _validate_current(self, evidence: dict, ref: str, *, task: Optional[dict] = None) -> list:
        reasons = []
        task = task if task is not None else self.store.read(ref)
        mappings = task.get("meta", {}).get("templates", {}).get("artifact_map", {})
        for validates in evidence.get("validates", []):
            artifact = validates.get("artifact")
            artifact_map = mappings.get(artifact, {})
            file_mode = mappings.get("mode") == "file"
            path = None
            text = None
            try:
                path = self.store.project_file(artifact)
                if not path.is_file():
                    raise DomainError("artifact_missing", "Artifact does not exist", {"artifact": artifact})
                text = _normal_text(path)
            except DomainError as exc:
                reasons.append({"type": "artifact", "artifact": artifact, "reason": exc.code})
                continue
            if file_mode:
                # Whole-file conservative mode: the current file content must
                # hash exactly as recorded for every validated item; no
                # item-scoped or dependency reasoning applies.
                current_digest = hashlib.sha256(text.encode()).hexdigest()
                for entry in validates.get("items", []):
                    if entry.get("sha256") != current_digest:
                        reasons.append({"type": "item", "artifact": artifact, "item": entry.get("id")})
                continue
            # Transitive closure: an item is checked when it is referenced
            # directly or appears anywhere in the dependency closure of the
            # referenced items. Missing/colliding dependency IDs are explicit
            # staleness reasons, never silently ignored.
            direct = {item["id"]: item["sha256"] for item in validates.get("items", [])}
            closure = {}
            for item_id in list(direct):
                pending = [item_id]
                seen = set()
                while pending:
                    current_id = pending.pop()
                    if current_id in seen:
                        continue
                    seen.add(current_id)
                    spec = artifact_map.get(current_id)
                    if spec is None:
                        if current_id not in direct:
                            reasons.append({"type": "dependency_missing", "artifact": artifact, "item": current_id})
                        continue
                    for dependency in spec.get("dependencies", []):
                        pending.append(dependency)
                for reachable in seen:
                    if reachable in closure:
                        continue
                    try:
                        digest = _extract_item(text, artifact_map, reachable)
                    except DomainError as exc:
                        reasons.append({"type": "mapping", "artifact": artifact, "item": reachable, "reason": exc.code})
                        continue
                    if digest is None:
                        reasons.append({"type": "dependency_missing", "artifact": artifact, "item": reachable})
                        continue
                    closure[reachable] = digest
            for item_id, expected in direct.items():
                if closure.get(item_id) != expected:
                    reasons.append({"type": "item", "artifact": artifact, "item": item_id})
            for item_id, digest in closure.items():
                if item_id in direct:
                    continue
                recorded = next((entry.get("sha256") for entry in validates.get("dependencies", []) if entry.get("id") == item_id), None)
                if recorded is None:
                    reasons.append({"type": "dependency_unbound", "artifact": artifact, "item": item_id})
                elif recorded != digest:
                    reasons.append({"type": "dependency_changed", "artifact": artifact, "item": item_id})
        for entry in evidence.get("input_files", []):
            relative = entry.get("path")
            try:
                path = self.store.project_file(relative)
                if not path.is_file() or file_digest(path) != entry.get("sha256"):
                    reasons.append({"type": "input_file", "path": relative})
            except (DomainError, OSError, ValueError, TypeError, RuntimeError):
                reasons.append({"type": "input_file", "path": relative})
        delivery = evidence.get("delivery")
        if delivery:
            current = self.delivery_snapshot([entry["path"] for entry in delivery.get("paths", [])])
            if current["digest"] != delivery.get("digest"):
                reasons.append({"type": "delivery", "expected": delivery.get("digest"), "actual": current["digest"]})
        report = evidence.get("report")
        if report:
            path = self.store.project_file(report.get("path", ""))
            if not path.is_file() or file_digest(path) != report.get("sha256"):
                reasons.append({"type": "report", "path": report.get("path")})
        return reasons

    def record(self, ref: str, *, evidence: dict, lease_token: str) -> dict:
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "Evidence cannot be recorded for a dropped task", status=3)
            lease = task.get("lease")
            if not lease or lease.get("token") != lease_token:
                raise DomainError("invalid_lease", "Evidence result has an old or missing lease token", status=4)
            if lease.get("expires_at", "") <= self.clock():
                raise DomainError("expired_lease", "Lease expired before evidence was recorded", status=4)
            item = dict(evidence)
            item.setdefault("id", str(uuid.uuid4()))
            item.setdefault("produced_at", self.clock())
            item.setdefault("state", "valid")
            for required in ("kind", "producer", "validates"):
                if required not in item:
                    raise DomainError("invalid_evidence", "Evidence is missing a required field", {"field": required})
            if not isinstance(item.get("producer"), dict) or not isinstance(item["validates"], list):
                raise DomainError("invalid_evidence", "Evidence producer must be an object and validates an array")
            for group in item["validates"]:
                if not isinstance(group, dict) or not isinstance(group.get("artifact"), str) or not isinstance(group.get("items"), list):
                    raise DomainError("invalid_evidence", "Each validates entry requires an artifact path and item list")
                if not all(isinstance(entry, dict) and isinstance(entry.get("id"), str) and isinstance(entry.get("sha256"), str) for entry in group["items"]):
                    raise DomainError("invalid_evidence", "Validated items require string id and sha256")
            if item["kind"] == "check":
                if not isinstance(item.get("items"), list) or not all(isinstance(entry, dict) for entry in item["items"]):
                    raise DomainError("invalid_check", "Check items must be an array of objects")
                self._validate_check(item, task)
            reasons = self._validate_current(item, ref)
            if reasons:
                item["state"] = "stale"
                item["stale_reasons"] = reasons
            task["evidence"].append(item)
            task["events"].append({"id": str(uuid.uuid4()), "at": self.clock(), "source": item["producer"], "type": "evidence_added", "data": {"evidence_id": item["id"], "state": item["state"]}})
            task["lease"]["expires_at"] = _plus_minutes(self.clock(), 30)
            self.store.write(task_dir, task)
            return item

    def _validate_check(self, item: dict, task: Optional[dict] = None) -> None:
        producer = item.get("producer", {})
        if producer.get("role") != "check":
            raise DomainError("invalid_check_producer", "Check evidence must be produced by the check role")
        if item.get("scope") not in {"incremental", "final"}:
            raise DomainError("invalid_check", "Check evidence requires an incremental or final scope")
        if not item.get("run_id") or not item.get("environment") or not item.get("delivery") or not item.get("items"):
            raise DomainError("invalid_check", "Check evidence lacks run, environment, delivery, or item details")
        validated_ids = {entry.get("id") for group in item.get("validates", []) for entry in group.get("items", [])}
        covered_ids = set()
        for result in item["items"]:
            if result.get("result") not in {"passed", "failed", "blocked", "skipped", "not_run"}:
                raise DomainError("invalid_check_result", "Unknown check item result")
            if not result.get("plan_item") or not result.get("requirement_ids"):
                raise DomainError("invalid_check_scope", "Each check item must reference an established plan item and requirement ids")
            covered_ids.update(result.get("requirement_ids", []))
            if result.get("result") == "passed" and not (result.get("command") or result.get("review_method")):
                raise DomainError("invalid_check_result", "Passed items require an executed command or review method")
        if not validated_ids or not validated_ids <= covered_ids:
            raise DomainError("invalid_check_scope", "Final check coverage must be bound to the established validated requirement scope", {"validated": sorted(validated_ids), "covered": sorted(covered_ids)})
        if task is not None:
            # Scope is established before the report: every validated item id
            # must already exist in the persisted artifact map. A report cannot
            # invent its own coverage.
            mappings = task.get("meta", {}).get("templates", {}).get("artifact_map", {})
            file_mode = mappings.get("mode") == "file"
            for group in item.get("validates", []):
                artifact = group.get("artifact")
                if artifact not in mappings:
                    raise DomainError("invalid_check_scope", "Check validates an artifact outside the established artifact map", {"artifact": artifact})
                if file_mode:
                    continue
                known = set(mappings.get(artifact, {}) if isinstance(mappings.get(artifact), dict) else {})
                unknown = {entry.get("id") for entry in group.get("items", [])} - known
                if not known or unknown:
                    raise DomainError("invalid_check_scope", "Check validates items outside the established artifact map", {"artifact": artifact, "unknown": sorted(unknown)})
            # The final independent check cannot come from the same writer that
            # produced the delivery evidence: producer ids must differ.
            implementers = {entry.get("producer", {}).get("id") for entry in task.get("evidence", []) if entry.get("kind") == "delivery"}
            if producer.get("id") in implementers:
                raise DomainError("check_not_independent", "The final check must come from a producer distinct from the delivery implementer", status=3)
        # S-4 K-2: the final check is read-only. It must declare
        # read_only=true, and the current delivery baseline must still be
        # fresh (a changed delivery means the check no longer describes the
        # work awaiting acceptance). Incremental checks are unaffected.
        if item.get("scope") == "final":
            if item.get("read_only") is not True:
                raise DomainError("invalid_check", "A final check must declare read_only: true")
            if task is not None:
                stale_reasons = self.final_delivery_current(task=task)
                if stale_reasons:
                    raise DomainError("final_check_stale_delivery",
                                      "The delivery evidence is no longer current; record a fresh delivery before the final check",
                                      {"stale_reasons": stale_reasons}, status=3)

    def invalidate(self, ref: str, *, file: str, actor: dict) -> dict:
        changed = []
        with self.store.transaction():
            task_dir = self.store.resolve(ref)
            task = self.store._read_path(task_dir / "task.json")
            if task.get("meta", {}).get("disposition"):
                raise DomainError("task_dropped", "Evidence cannot be invalidated on a dropped task", status=3)
            lease = task.get("lease")
            if lease and lease.get("expires_at", "") > self.clock():
                raise DomainError("lease_conflict", "Evidence invalidation cannot race an active writer", {"holder": lease.get("holder")}, status=4)
            for evidence in task["evidence"]:
                if evidence.get("state") != "valid":
                    continue
                relevant = any(v.get("artifact") == file for v in evidence.get("validates", [])) or any(p.get("path") == file for p in evidence.get("delivery", {}).get("paths", [])) or any(p.get("path") == file for p in evidence.get("input_files", [])) or evidence.get("report", {}).get("path") == file
                if relevant:
                    reasons = self._validate_current(evidence, ref)
                    if reasons:
                        evidence["state"] = "stale"
                        evidence["stale_reasons"] = reasons
                        changed.append(evidence["id"])
            if changed:
                task["events"].append({"id": str(uuid.uuid4()), "at": self.clock(), "source": actor, "type": "evidence_invalidated", "data": {"file": file, "evidence_ids": changed}})
                if task["phase"] == "completed":
                    task["phase"] = "in_progress"
                    task["completedAt"] = None
                    if task["acceptance"]:
                        task["acceptance"]["state"] = "stale"
                elif task["phase"] == "awaiting_acceptance":
                    # The acceptance basis is gone: the task is no longer
                    # awaiting acceptance. It returns to in_progress so the
                    # coordinator can run a fresh check and re-enter the
                    # phase (the transition stays explicit).
                    task["phase"] = "in_progress"
                self.store.write(task_dir, task)
        return {"invalidated": changed}

    def invalidate_scope(self, task: dict, *, reason: str, scope: Optional[dict] = None) -> dict:
        """Invalidate evidence by rework scope (S-4 K-1); shared logic for
        both rework entry points (report_problem and continue --action rework).

        ``scope=None`` (or ``mode="full"``) keeps the legacy behavior: every
        valid evidence goes stale. ``mode="localized"`` stales only evidence
        intersecting the declared artifacts/paths/criteria_refs; untouched
        evidence stays valid. The task dict is mutated IN PLACE under the
        caller's own transaction (no nested lock), and the audit split of
        invalidated and retained ids is returned so the rework event can
        carry both.
        """
        normalized = validate_rework_scope(scope)
        changed = []
        retained = []
        if task.get("meta", {}).get("disposition"):
            raise DomainError("task_dropped", "Evidence cannot be invalidated on a dropped task", status=3)
        for evidence in task["evidence"]:
            if evidence.get("state") != "valid":
                continue
            if normalized["mode"] == "full" or _rework_scope_touches(evidence, normalized):
                evidence["state"] = "stale"
                evidence["stale_reasons"] = [{"type": "rework_requested", "reason": reason}]
                changed.append(evidence["id"])
            else:
                retained.append(evidence["id"])
        return {"scope": normalized, "invalidated_evidence_ids": changed, "retained_evidence_ids": retained}

    def final_delivery_current(self, ref: Optional[str] = None, *, task: Optional[dict] = None) -> list:
        """Staleness reasons across the current effective delivery baseline.

        The baseline is PER PATH (S-4 K-2/coordination): for every delivered
        path, the newest delivery evidence that covered it is the effective
        baseline for that path. A repaired path therefore supersedes the older
        stale snapshot for that path only, so a fix recorded after a failed
        check is never permanently blocked by the superseded snapshot, while
        the paths nobody re-delivered still report their drift. Pure read;
        returns the staleness reasons (empty means fresh).
        """
        task = task if task is not None else self.store.read(ref)
        latest = {}
        for evidence in task.get("evidence", []):
            if evidence.get("kind") != "delivery":
                continue
            produced = str(evidence.get("produced_at", ""))
            for entry in (evidence.get("delivery") or {}).get("paths", []):
                relative = entry.get("path")
                if relative is None:
                    continue
                previous = latest.get(relative)
                if previous is None or produced >= previous[0]:
                    latest[relative] = (produced, entry)
        reasons = []
        for relative in sorted(latest):
            _, entry = latest[relative]
            path = self.store.project_file(relative)
            exists = path.is_file()
            current = file_digest(path) if exists else None
            if exists != bool(entry.get("exists")) or current != entry.get("sha256"):
                reasons.append({"type": "delivery", "path": relative,
                                "expected": entry.get("sha256"), "actual": current})
        return reasons

    def freshness(self, ref: Optional[str] = None, *, task: Optional[dict] = None) -> dict:
        task = task if task is not None else self.store.read(ref)
        results = []
        for item in task["evidence"]:
            reasons = self._validate_current(item, ref) if item.get("state") == "valid" else item.get("stale_reasons", [{"type": "recorded_stale"}])
            results.append({"id": item.get("id"), "fresh": not reasons and item.get("state") == "valid", "reasons": reasons})
        return {"task_id": task["id"], "evidence": results}

    def acceptance_status(self, ref: Optional[str] = None, *, task: Optional[dict] = None) -> dict:
        task = task if task is not None else self.store.read(ref)
        fresh_results = {x["id"]: x for x in self.freshness(ref, task=task)["evidence"]}
        # A rework retires the acceptance basis (S-4 K-1). Evidence that a
        # localized rework retained stays valid AS EVIDENCE (it can still be
        # cited, re-checked or audited), but it must not by itself re-enable
        # acceptance: a check recorded BEFORE the rework says nothing about
        # the repaired work, so the rework loop could otherwise be closed
        # without a single new check. A final check recorded after the rework
        # is required to accept again. The retirement is read from the
        # rework_requested milestone (never compacted away), so a task that
        # never had a rework is unaffected.
        retired_by_rework = set()
        for event in task.get("events", []):
            if event.get("type") == "rework_requested":
                retired_by_rework |= set(event.get("data", {}).get("retained_evidence_ids", []))
        final_checks = []
        # Governance (design §5.2): the newest final check for the task governs
        # acceptance; an unresolved fail/blocked/not_run in that latest round
        # cannot be overridden by an older passed round.
        latest_final = None
        for item in task["evidence"]:
            if item.get("kind") == "check" and item.get("scope") == "final":
                latest_final = item
        for item in task["evidence"]:
            if item.get("kind") != "check" or item.get("scope") != "final":
                continue
            states = [entry.get("result", "not_run") for entry in item.get("items", [])]
            current_fresh = bool(fresh_results.get(item.get("id"), {}).get("fresh", False))
            superseded = current_fresh and latest_final is not None and item.get("id") != latest_final.get("id")
            retired = item.get("id") in retired_by_rework
            effective_pass = bool(states) and all(x == "passed" for x in states) and current_fresh and not superseded and not retired
            final_checks.append({"id": item.get("id"), "fresh": current_fresh and not superseded, "superseded": superseded, "retired_by_rework": retired, "results": states, "passed": effective_pass,
                                 "run_id": item.get("run_id"), "environment": item.get("environment"),
                                 "delivery": item.get("delivery"), "items": item.get("items", []),
                                 "validates": item.get("validates", []), "producer": item.get("producer"),
                                 "report": item.get("report"), "stale_reasons": fresh_results.get(item.get("id"), {}).get("reasons", [])})
        lease = task.get("lease")
        active_lease = bool(lease and lease.get("expires_at", "") > self.clock())
        blockers = []
        if task.get("blocked"):
            blockers.append("blocked")
        if active_lease:
            blockers.append("active_lease")
        if task.get("meta", {}).get("disposition"):
            blockers.append("dropped")
        if latest_final is not None:
            latest_states = [entry.get("result", "not_run") for entry in latest_final.get("items", [])]
            if not latest_states or any(state != "passed" for state in latest_states):
                blockers.append("unresolved_check")
        qualifying = [x for x in final_checks if x["fresh"] and x["passed"]]
        if retired_by_rework and not qualifying:
            # The only final checks this task has are pre-rework ones: the
            # rework loop needs a NEW final check before acceptance.
            blockers.append("rework_requires_new_check")
        return {"task_id": task["id"], "checks": final_checks, "evidence_refs": [x["id"] for x in qualifying], "awaiting_acceptance": bool(qualifying) and not blockers, "blockers": blockers}


def _plus_minutes(value: str, minutes: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    from datetime import timedelta
    return (parsed + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
