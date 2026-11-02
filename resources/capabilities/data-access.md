# Capability: data access

id: data-access
roles: research / implement / check
schema: fstar.capability.v1

## Definition

Inspect a data source: schema, metadata, and read-only queries. The capability
describes a tool's access boundary and proven connection; it never authorizes
writes or schema changes.

## Decidable criteria

- The connection is proven by a successful minimal exchange, not by a
  configuration entry.
- Read-only permission and the schema/query boundary are explicit.
- Query failures are distinguishable from empty results.

## Three-layer verification

1. Discoverable: the database client or MCP server exists on this machine.
2. Client loaded: the client/transport is available and authentication is
   accepted; a stored credential alone is not evidence.
3. Minimal real call: inside the user-granted read-only scope, run one
   minimal query (for example `select 1` or a schema listing) against the
   intended data source. A write statement is never a verification probe.

## Recommended implementation

DBHub or `psql` in read-only mode, or a read-only export/schema dump for
offline work.

## Common non-qualifying implementations

- `insert`, `update`, `delete`, or DDL executed as a "test".
- Treating a reachable port or a stored DSN as a successful data query.
- Presenting cached or exported data as a live connection.

## Fallback

Use a read-only export or schema documentation and mark it non-realtime; never
execute write SQL as a probe. State clearly which facts are from the export and
which are unverified for the live source.

## Recording requirements

Record capability, tool and version, the read-only boundary, a sanitized query
summary (never credentials or row data), the call identity, and the fallback in
the task ``capabilities[]`` provenance.
