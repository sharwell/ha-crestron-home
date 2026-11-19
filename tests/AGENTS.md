# Testing the Home Assistant integration

- Use meaningful regression, boundary, and failure scenarios with the changes
  they protect. Documentation-only and reversible, low-impact edits can use
  checks that establish something beyond restating the prose or implementation.
- Exercise production connection and discovery logic, entities, protocol
  parsers, and other behavior through normal public paths and framework state.
  Assert useful results, errors, entity states, availability, events, emitted
  commands, and persistent effects, including sequence when contractually
  significant. Avoid private helper assertions, incidental ordering or counts,
  and whole-output snapshots unless the detail is part of the contract. Explain
  internal assertions that protect ownership, resource limits, or security.
- Prefer real Home Assistant fixtures for config entries, registries, entity
  lifecycle, state restoration, the state machine, and the event bus. Keep
  existing lightweight tests usable. Justify added isolation, including
  framework stubs, with a demonstrated failure, measured cost, uncontrolled
  state, or concrete evidence of a predicted risk. Convenience and general
  concerns about speed are insufficient.
- Keep production logic in the path and share small, faithful fakes at actual
  external boundaries such as the Crestron HTTP transport. Preserve relevant
  failures, notifications, ordering, connection ownership, cancellation,
  disconnect, and completion. Use real temporary files where practical for file
  behavior. Use a scenario-specific override only when normal inputs or a
  shared fake cannot exercise an essential case. A focused mock can verify
  that a prohibited operation never occurs.
- Prefer explicit clocks, events, and controlled fixtures to sleeps. Bound
  waits and release test resources. When controlling time or shortening waits,
  preserve the relationships among operation deadlines, cleanup budgets,
  retries, and watchdogs. Preserve genuine randomness when testing independent
  keys or tokens. Use distinguishable data from old and replacement sessions or
  connections to expose stale callbacks, ownership errors, and recovery races.
- Derive expectations independently from the implementation. If testing
  recognition, keep training, tuning, and held-out evaluation distinct. Name
  tests by condition and expected outcome. Explain subtle user or caller risks
  and make failures informative. Use fictional fixtures without private
  configuration or live access. Preserve assertion strength and security
  checks when fixing a failure.
- Report tests actually run separately from formatting, fixture generation,
  compilation, synthetic input, and device acceptance. Report unavailable
  checks as unverified. A simulated call or completed task cannot establish
  real connection cleanup or physical movement. Verify such claims at the
  relevant transport or hardware boundary. Broaden or repeat checks for a new
  change, a failure, or a remaining concern.
