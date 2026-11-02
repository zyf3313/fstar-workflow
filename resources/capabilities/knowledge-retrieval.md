# Capability: knowledge retrieval

id: knowledge-retrieval
roles: research / implement / check
schema: fstar.capability.v1

## Definition

Recall decisions, documents, and prior facts that already exist in the project
or in long-term knowledge. The capability describes the retrieval tool's
reach, freshness, and routes; whether a recalled document is still the right
authority remains a reading judgment.

## Decidable criteria

- Collection freshness is observable (index time or content timestamps).
- Both routes are reportable where claimed: keyword/exact lookup and semantic
  lookup.
- Every result carries a verifiable source path.

## Three-layer verification

1. Discoverable: the index or retrieval tool exists on this machine.
2. Client loaded: the client can query the collection and does not report it
   missing; a config entry alone is not loading.
3. Minimal real call: query one known local document and confirm it is
   returned with its source path and current freshness. A missing index is a
   failed or unknown fact, not an empty result set.

## Recommended implementation

A project knowledge index (QMD or the project's existing index) and plain
full-text search over the knowledge directories.

## Common non-qualifying implementations

- Recursive `grep` over arbitrary files presented as verified semantic
  retrieval.
- An index directory existing on disk presented as a fresh, complete index.
- Returning generated summaries without the source path.

## Fallback

Fall back to index or text queries and itemize the missing semantic route or
the unverified freshness per source. A degraded retrieval is still a real
retrieval when its route and limitations are stated.

## Recording requirements

Record capability, tool and version, the query route, the source path, the
freshness evidence, the call identity, and the fallback in the task
``capabilities[]`` provenance.
