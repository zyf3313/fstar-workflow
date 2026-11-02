# Capability: web research

id: web-research
roles: research / implement / check
schema: fstar.capability.v1

## Definition

Answer questions that depend on the outside world: the current version of a
dependency, official documentation, or facts from an upstream repository. The
capability describes what a tool can do; it does not claim that every result is
correct or recent.

## Decidable criteria

- The original source is readable; a secondary summary alone is not enough.
- Version and provenance (repository, release, document revision) are
  traceable to the answer.
- The tool reports when a page or repository is unreachable instead of
  silently substituting a cached copy.

## Three-layer verification

1. Discoverable: the research tool (host search, `gh`, an MCP server) is
   present on this machine.
2. Client loaded: the client lists the tool and does not report missing
   authentication or an unavailable transport.
3. Minimal real call: read one known source the user task actually needs and
   record the URL, version, and access time. Reading a random page is not
   sufficient evidence for a specific task.

## Recommended implementation

Host web search, `gh` for repository facts, or a configured research MCP
server. Recommended by the package; binding stays with the user.

## Common non-qualifying implementations

- Summaries presented without a source or date.
- A search result count shown as proof that the latest version was checked.
- Treating a configured API key as proof of a working query.

## Fallback

Use local material or an existing cache with explicit dates; state that the
latest upstream version or original source could not be verified. Never
present stale material as current.

## Recording requirements

Record capability, tool and version, the source URL/version and access time,
the call identity, and any fallback or stale-source note in the task
``capabilities[]`` provenance.
