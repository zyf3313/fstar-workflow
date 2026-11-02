# Capability: test execution

id: test-execution
roles: research / implement / check
schema: fstar.capability.v1

## Definition

Run tests and report real results: the command, exit code, and locatable
failures. The capability describes the runner and the reproducibility of its
result; it does not decide whether a passing suite satisfies a requirement.

## Decidable criteria

- An executable command is recorded, not just a runner name.
- The result is reproducible from the recorded command and environment.
- Failures are locatable (test name, assertion, file:line or report path).
- A "not run" outcome is reported as not run.

## Three-layer verification

1. Discoverable: the runner/executable exists on this machine.
2. Client loaded: the runner can start in the target environment and reports
   its own configuration (for example `--version`).
3. Minimal real call: run one known test inside an isolated fixture. Running
   arbitrary project tests is not a side-effect-free probe; the host must
   confirm the scope before choosing the fixture.

## Recommended implementation

The project's own test runner with its documented command. Do not replace it
with a package default when the project already declares one.

## Common non-qualifying implementations

- Static checks or a "would pass" claim presented as a test result.
- A test report copied from an older revision.
- Running the whole suite in an unknown environment and calling it isolated.

## Fallback

Use static checks with an explicit not-run marker; never report unexecuted
tests as passing. A failed run is recorded with its reason and exit code and
is not converted into a verified layer by a later unrelated observation.

## Recording requirements

Record capability, tool and version, the command, exit code, failing test
locations, environment/run id, the call identity, and the fallback in the task
``capabilities[]`` provenance. A passing test is evidence for review, not an
independent check or user acceptance.
