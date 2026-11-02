# Capability: code structure

id: code-structure
roles: research / implement / check
schema: fstar.capability.v1

## Definition

Answer structural questions about code: where a symbol is defined, who calls
it, and what a change would affect. The capability describes what a tool can
do; product quality, review findings, or documentation style are not part of
it. UI tools are not a sixth capability.

## Decidable criteria

- Symbol-level lookup: definitions, references, and the impact set.
- Every result is traceable to a concrete `file:line`.
- The tool distinguishes "the symbol does not exist" from "the workspace is
  not indexed" instead of returning an empty success for both.

Plain literal search fails these criteria: it cannot answer reference or
impact questions even when it finds a matching line.

## Three-layer verification

1. Discoverable: the bound target exists on this machine (executable, MCP
   server entry, or installed skill).
2. Client loaded: the client can list the tool's symbols/queries and does not
   report the workspace as unindexed.
3. Minimal real call: query one known symbol and confirm the returned
   definition matches the source (`file:line` content). Success at layer 1 or
   2 never proves this layer.

## Recommended implementation

CodeGraph or a language server exposing symbol lookup. Users may override the
binding with a documented reason; the override does not rewrite this contract.

## Common non-qualifying implementations

- Plain text/regex search presented as structure retrieval.
- A tool whose only evidence is a config file, a running process, or an
  earlier scan snapshot.
- An MCP server that is reachable but reports the current workspace unindexed.

## Fallback

Literal text search locates text only; it cannot claim a verified call graph
or impact set. State the gap explicitly instead of presenting text matches as
structural results. Whether the remaining work is acceptable is decided by
the caller against the actual task requirement, not written automatically as
blocked or accepted.

## Recording requirements

Record capability, actual tool, tool version (null when unknown), match basis,
call identity and source, availability result, and any fallback in the task
``capabilities[]`` provenance. A binding or a successful lookup is not an
independent check or user acceptance.
