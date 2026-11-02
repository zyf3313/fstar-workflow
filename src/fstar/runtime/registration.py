"""Read-only host registration shapes for the four semantic hooks.

``fstar hook plan --host claude|codex`` outputs the registration entries this
package would need on that host. It never writes host settings: the actual
append/dedup/uninstall belongs to package-install (child design §7). Every
entry carries the exact fields needed for append-with-dedup (dedup key =
event + command) and for precise removal of only fstar's own entries.

Host event names below are implementation-time verified facts where marked;
unverified payload assumptions keep ``to_verify`` flags and the hook logic
itself runs identically at dispatch/recovery/command boundaries when a host
event is unavailable (see hooks.HOST_EVENT_MAP).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from ..models import DomainError

HOOK_SEMANTICS = ("session-context", "worker-context", "worker-result", "doc-change")

# The command line the host would execute for each semantic hook. The
# installed launcher (bin/fstar-hook.cjs) is what package-install actually
# registers (installer._hook_command); the ``fstar hook <name>`` CLI entry is
# the same code path the boundary fallback uses, so host-event and fallback
# execution cannot diverge. The launcher path is resolved from this package's
# real location (npm bin symlink compatible); when the launcher file is not
# present next to the package (source checkout without bin/), the plan keeps
# the interpreter form and says so — it never claims an installed launcher
# that does not exist on disk.
def _launcher_command(semantic: str) -> Tuple[str, bool]:
    launcher = Path(__file__).resolve().parents[3] / "bin" / "fstar-hook.cjs"
    if launcher.is_file():
        return "%s %s" % (installer_shell_quote(str(launcher)), semantic), True
    return "python3 -m fstar.runtime %s" % semantic, False


def installer_shell_quote(value: str) -> str:
    """POSIX single-quote encoding for the fixed launcher path.

    Same rules as the installer's hook command: the path is a package
    constant, no user text is interpolated, and anything outside the safe set
    is single-quoted.
    """
    if not value:
        return "''"
    if all((char.isascii() and char.isalnum()) or char in "@%+=:,./-_" for char in value) \
            and not value.startswith("-"):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _hook_commands() -> Dict[str, Tuple[str, bool]]:
    return {semantic: _launcher_command(semantic) for semantic in HOOK_SEMANTICS}

# Claude Code settings.json shape (verified against Claude Code 2.1.312 and
# the locally registered hooks in this repository's .claude/settings.json):
# {"hooks": {"<EventName>": [{"matcher": ..., "hooks": [{"type": "command",
# "command": ..., "timeout": ...}]}]}}. Entries append to the arrays; dedup
# key = event + command.
CLAUDE_PLAN = [
    {
        "host": "claude",
        "settings_path": "~/.claude/settings.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "SessionStart",
        "semantic": "session-context",
        "matchers": ["startup", "clear", "compact"],
        "hooks": [{"type": "command", "command": "@@session-context@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [],
    },
    {
        "host": "claude",
        "settings_path": "~/.claude/settings.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "PreToolUse",
        "semantic": "worker-context",
        "matchers": ["Task", "Agent"],
        "hooks": [{"type": "command", "command": "@@worker-context@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [],
    },
    {
        "host": "claude",
        "settings_path": "~/.claude/settings.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "SubagentStop",
        "semantic": "worker-result",
        "matchers": [],
        "hooks": [{"type": "command", "command": "@@worker-result@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [
            "SubagentStop payload does not carry the dispatch result message; the "
            "runtime-dispatch recovery boundary remains the primary worker-result caller",
        ],
    },
    {
        "host": "claude",
        "settings_path": "~/.claude/settings.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "PostToolUse",
        "semantic": "doc-change",
        "matchers": ["Edit", "Write"],
        "hooks": [{"type": "command", "command": "@@doc-change@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [],
    },
]

# Codex shape (verified against codex-cli 0.165.0: the app-server protocol
# schema exposes HookEventName enum values sessionStart/preToolUse/
# postToolUse/subagentStart/subagentStop, and observed project registrations
# use .codex/hooks.json with PascalCase keys mirroring Claude's shape, with
# ~/.codex/config.toml [hooks.state] trust keys using snake_case event ids).
CODEX_PLAN = [
    {
        "host": "codex",
        "settings_path": "<project>/.codex/hooks.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "SessionStart",
        "semantic": "session-context",
        "schema_event": "sessionStart",
        "matchers": [],
        "hooks": [{"type": "command", "command": "@@session-context@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [
            "sessionStart exists in the HookEventName enum but no live registration was "
            "observed; hooks.json key casing and payload shape are to-verify",
        ],
        "fallback": "fstar hook session-context invoked manually or by the entry skill",
    },
    {
        "host": "codex",
        "settings_path": "<project>/.codex/hooks.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "SubagentStart",
        "semantic": "worker-context",
        "schema_event": "subagentStart",
        "matchers": [],
        "hooks": [{"type": "command", "command": "@@worker-context@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [
            "payload carries agent_type/agentType plus the parent session_id; the role "
            "mapping from agent_type to fstar roles is adapter-level and to-verify",
        ],
        "fallback": "runtime-dispatch dispatch wrapper invokes the same worker-context entry",
    },
    {
        "host": "codex",
        "settings_path": "<project>/.codex/hooks.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "SubagentStop",
        "semantic": "worker-result",
        "schema_event": "subagentStop",
        "matchers": [],
        "hooks": [{"type": "command", "command": "@@worker-result@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": True,
        "to_verify": [
            "subagentStop payload shape is not exposed by the generated protocol schema; "
            "it cannot carry the dispatch result message, so the runtime-dispatch "
            "recovery boundary remains the primary worker-result caller",
        ],
        "fallback": "runtime-dispatch recovery boundary invokes the same worker-result entry",
    },
    {
        "host": "codex",
        "settings_path": "<project>/.codex/hooks.json",
        "location": "hooks.<EventName>[] (append, never overwrite other entries)",
        "dedup_key": "event + command",
        "event": "PostToolUse",
        "semantic": "doc-change",
        "schema_event": "postToolUse",
        "matchers": [],
        "hooks": [{"type": "command", "command": "@@doc-change@@", "timeout": 30}],
        "owned_by": "fstar",
        "verified": False,
        "to_verify": [
            "postToolUse exists in the HookEventName enum but its payload's file-path "
            "key is not exposed by the generated schema; the doc path extraction is "
            "to-verify on a real codex run",
        ],
        "fallback": "fstar evidence invalidate plus core read-boundary recalculation (already implemented in core)",
    },
]

PLANS: Dict[str, list] = {"claude": CLAUDE_PLAN, "codex": CODEX_PLAN}

_LAUNCHER_NOTE = ("command references the packaged bin/fstar-hook.cjs launcher, "
                  "the same executable package-install registers")
_INTERPRETER_NOTE = ("bin/fstar-hook.cjs is not present beside this package; the "
                     "interpreter form is shown. The npm package install registers "
                     "the packaged launcher instead.")


def _resolve_entry(entry: dict, commands: Dict[str, Tuple[str, bool]]) -> dict:
    """Materialize one plan entry with its real command and honest evidence.

    ``verified`` keeps its implementation-time meaning: the host settings
    shape/event name was observed (observed-schema), never that the host
    delivered a live hook invocation. ``launcher_installed`` reports whether
    the referenced launcher file actually exists on disk.
    """
    resolved = dict(entry)
    hooks = []
    for hook in entry.get("hooks", []):
        hook = dict(hook)
        semantic = hook["command"].strip("@")
        command, installed = commands[semantic]
        hook["command"] = command
        hook["launcher_installed"] = installed
        hook["evidence"] = "observed-schema" if entry.get("verified") else "unverified-schema"
        hooks.append(hook)
    resolved["hooks"] = hooks
    resolved["launcher_note"] = _LAUNCHER_NOTE if all(
        hook["launcher_installed"] for hook in hooks) else _INTERPRETER_NOTE
    return resolved


def plan(host: str) -> dict:
    """Read-only registration shapes for one host. Never writes settings."""
    if host not in PLANS:
        raise DomainError("unknown_host", "Unknown host for hook registration plan", {"host": host, "hosts": sorted(PLANS)})
    commands = _hook_commands()
    entries = [_resolve_entry(entry, commands) for entry in PLANS[host]]
    return {
        "host": host,
        "read_only": True,
        "written_by": "package-install",
        "dedup_key": "event + command",
        "uninstall": ("package-install removes only entries recorded in its own install "
                      "manifest that still match the recorded baseline (full event+matcher+"
                      "command+options value); user and unknown entries are never touched. "
                      "This plan itself never writes or removes settings."),
        "entries": entries,
    }
