"""Internal tools skill binding bridge; grants are cooperative routing context."""
import json
import re
import sys
from contextlib import nullcontext
from pathlib import Path

from . import tools
from .extensions import grants, includes
from .models import DomainError
from .store import TaskStore
from .tasks import utc_now


def run(request):
    if not isinstance(request, dict):
        raise DomainError("tools_invalid_request", "Request must be an object")
    action = request.get("action")
    if action not in ("prepare", "apply", "contract", "assess", "provenance"):
        raise DomainError("tools_invalid_request", "Unknown tools bridge action")
    def root(name):
        value = request.get(name)
        if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
            raise DomainError("tools_invalid_request", name + " must be an absolute path")
        return Path(value).resolve()
    project, user, runtime = root("project_root"), root("user_root"), root("runtime_root")
    ref = request.get("task_ref")
    if not isinstance(ref, str) or not ref.strip():
        raise DomainError("task_required", "Explicit task_ref is required")
    records = request.get("extensions", [])
    store = None
    if ref != "session-only":
        if records:
            raise DomainError("invalid_extension", "Persistent tasks use stored grants")
        store = TaskStore(project, user_home=user, runtime_root=runtime)
        store.require_project()
    def authorize(members, task=None):
        current = (task if task is not None else store.read(ref))["extensions"] if store else records
        context = grants(current)
        for member in members:
            if not includes(context, "tool-capability", member):
                raise DomainError("extension_not_authorized", "Tool operation requires authorization",
                                  {"package": "tool-capability", "member": member}, status=3)
    if action == "contract":
        authorize(("contracts",))
        capability = request.get("capability")
        if not isinstance(capability, str) or capability not in tools.CAPABILITIES:
            raise DomainError("tools_invalid_request", "Unknown capability")
        from .installer import resources_root
        path = resources_root(project_root=project, user_root=user) / "capabilities" / (capability + ".md")
        contract = path.read_text(encoding="utf-8")
        context = grants(store.read(ref)["extensions"] if store else records)
        if not includes(context, "tool-capability", "fallback"):
            contract = re.sub(r"(?ms)^## Fallback\s*\n.*?(?=^## |\Z)", "", contract)
        return {"capability": capability, "contract": contract}
    if action in ("assess", "provenance"):
        required = ["bindings", "validation"]
        if action == "provenance" and isinstance(request.get("call_record"), dict) and request["call_record"].get("fallback"):
            required.append("fallback")
        authorize(required)
        def resolve_current():
            project_path = tools._target_path("project", user_root=user, project_root=project)
            user_path = tools._target_path("user", user_root=user, project_root=project)
            tools._reject_symlinks(project_path, project)
            tools._reject_symlinks(user_path, user)
            return tools.resolve_bindings(project=tools.load_tools(project_path), user=tools.load_tools(user_path))

        if action == "assess" or store is None:
            resolution = resolve_current()
            assessment = tools.assess_availability(resolution, request.get("observations", []))
        if action == "assess":
            # The provider bundles fallback text into gaps. Do not expose it unless granted.
            context = grants(store.read(ref)["extensions"] if store else records)
            if not includes(context, "tool-capability", "fallback"):
                for gap in assessment["gaps"]:
                    gap.pop("fallback", None)
            return {"resolution": resolution, "assessment": assessment}
        if store is None:
            record = tools.build_provenance(resolution, request.get("call_record"), assessment)
            selected = next(item for item in resolution["capabilities"] if item["capability"] == record["capability"])
            selected_tool = selected.get("tool")
            if selected["state"] != "bound" or not selected_tool or record["tool"] != selected_tool["tool"]:
                record["fallback"] = True
            if record["fallback"]:
                authorize(("fallback",))
            return {"record": record, "persistence": "caller"}

        def rebuild(task):
            # Runs under the task lock and the cooperating tools lock: reread the
            # binding layers and rebuild the record from the current state, so a
            # concurrent confirmed binding change cannot be committed as a stale
            # binding origin, selected tool, or fallback classification.
            fresh_resolution = resolve_current()
            fresh_assessment = tools.assess_availability(fresh_resolution, request.get("observations", []))
            fresh = tools.build_provenance(fresh_resolution, request["call_record"], fresh_assessment)
            fresh_selected = next(item for item in fresh_resolution["capabilities"]
                                  if item["capability"] == fresh["capability"])
            fresh_tool = fresh_selected.get("tool")
            if fresh_selected["state"] != "bound" or not fresh_tool or fresh["tool"] != fresh_tool["tool"]:
                fresh["fallback"] = True
            if fresh["fallback"]:
                authorize(("fallback",), task)
            return fresh

        return tools.record_provenance(store, ref, None, lease_token=request.get("lease_token"),
                                       clock=utc_now, authorize=lambda task: authorize(["bindings", "validation"], task),
                                       rebuild=rebuild, runtime_root=runtime)
    if action == "prepare":
        authorize(("bindings",))
        target = request.get("target")
        if target not in ("user", "project"):
            raise DomainError("tools_invalid_proposal", "target must be user or project")
        path = tools._target_path(target, user_root=user, project_root=project)
        tools._reject_symlinks(path, tools._root_for(target, user_root=user, project_root=project))
        proposal = tools.build_binding_proposal(target=target, loaded=tools.load_tools(path),
                                                changes=request.get("changes"), reason=request.get("reason"),
                                                tools=request.get("tools"))
        return {"proposal": proposal}
    confirmation = request.get("confirmation")
    if not isinstance(confirmation, dict):
        raise DomainError("tools_confirmation_required", "Explicit user confirmation is required", status=3)
    # Cooperating grant changes and the confirmed commit use the same task lock.
    with store.transaction() if store else nullcontext():
        authorize(("bindings",))
        return tools.apply_binding(request.get("proposal"), confirmation, clock=utc_now,
                                   user_root=user, project_root=project, runtime_root=runtime)


def main(argv=None):
    if argv:
        print(json.dumps({"ok": False, "error": {"code": "tools_invalid_request", "message": "No arguments supported", "details": {}}}))
        return 2
    try:
        result = run(json.load(sys.stdin))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except DomainError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, ensure_ascii=False))
        return exc.status
    except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "tools_invalid_request", "message": str(exc), "details": {}}}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
