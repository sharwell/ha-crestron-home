# Repository guidance

## Project and scope

- This is a HACS-distributed Python integration for Home Assistant. Implementation,
  the Home Assistant manifest, and UI strings live in
  `custom_components/crestron_home/`. The Matter hold/release automation is YAML
  under `blueprints/automation/crestron_home/`. User-facing guidance lives in
  `README.md` and `docs/OPTIONS_FLOW.md`.
- Before choosing an approach, read applicable instructions and inspect adjacent
  code, manifests, tooling, and contribution guidance. Follow Python, Home
  Assistant, and surrounding code conventions in their respective files.
- Keep changes tied to the requested outcome. Preserve unrelated work and avoid
  broad cleanup. These instructions confer no additional permission.
- When adding or changing behavior or regression coverage, read
  [the test guidance](tests/AGENTS.md). When writing or reviewing contracts for
  the integration, including in docs, read
  [the API guidance](custom_components/crestron_home/AGENTS.md).

## Documentation and review

- Identify the readers, their task, and the context they need without the
  original conversation. Lead with purpose, accurate scope, and the useful
  answer. Organize around reader tasks and give distinct reference tasks clear
  entry points. Use predictable sections with enough context for skimming.
- Put material qualifications beside the claims they change and an operation's
  constraints beside that operation. Later detail should refine the opening
  account. Review the whole piece and verify that individual statements hold
  up when read on their own.
- Scale detail to the task, audience, importance, and complexity. Keep facts
  and limitations when shortening. Label comparisons, units, and relationships
  directly. Use examples or tables when they save reader effort.
- Code and public interfaces establish implemented behavior and contracts.
  Maintained guides explain use of the supported branch or release. GitHub
  Issues hold detailed future scope and progress. Completed issues, PRs,
  commits, and prior revisions retain historical decisions and evidence.
  Open issues can describe current defects, and closed PRs can record rejected
  proposals. Treat closure as a record status and look for implementation evidence.
- Reuse useful summaries, links, and contracts at points of use while keeping
  their primary source clear. Weigh reader benefit against upkeep and avoid
  maintaining duplicate full accounts. For Options changes, keep visible
  labels and save, cancel, and undo behavior aligned across the applicable UI
  strings, README, and [Options flow guide](docs/OPTIONS_FLOW.md).
- Before an MVP, mark the project as pre-MVP and state what remains before
  intended use, the useful outcome, and where to find authoritative scope.
  Once the MVP is usable, lead with available capabilities and keep future plans
  easy to find. Overviews may summarize MVP requirements or link to an issue
  that explains a current limitation.
  Distinguish required outcomes, preferred representations, tentative or
  selected approaches, observed behavior, and accepted readiness. Label
  planned features and targets. Implementation and local results can leave
  deployment, device acceptance, or broader acceptance open.
- As behavior is implemented and accepted, preserve useful wording and
  structure. Update status, applicable versions, evidence, references, and
  changed contracts. Base status changes on implementation and acceptance
  evidence. The maintained guide or public contract becomes primary
  for current users while the completed work retains historical requirements
  and acceptance evidence. Remove superseded instructions from the active
  guide for the affected version. Keep history there when it serves current use,
  such as migration guidance, breaking changes, or an operative rationale or
  limitation. Use earlier revisions and completed work for other history.
- Use clear, familiar language, concrete examples, and the Oxford comma.
  Report the resulting behavior, material tradeoffs, validation, gaps, and
  remaining work with enough context for a new reader.
- Use concise, action-oriented PR titles naming the change and scope.
  Commit subject prefixes and length limits apply only to commit subjects.
  Keep titles and descriptions aligned with the final diff. Mention abandoned
  work only when it explains a decision the reviewer needs to assess. Present
  complete draft titles and bodies for review or label excerpts. Label
  alternatives consistently and use the agent's supported draft format.

## Development and GitHub planning

- Plan larger work in coherent, reviewable steps. State each step's purpose,
  observable outcome, actual dependencies, and how to check completion.
  Sequence alone creates no dependency. Work can span multiple commits, each
  with an understandable contribution.
- Put regression and failure coverage in the step that introduces the
  behavior. Reserve later validation for paths first testable at that point.
  Introduce tools, dependencies, runtime choices, modules, abstractions, and
  test infrastructure with their first real consumer. Keep completed steps
  loadable or buildable as appropriate and run their applicable checks.
- Distinguish plans and scaffolding from working capabilities. Update current
  contracts and usage guides as behavior changes. Identify the current
  development platform and intended deployment platform for multi-step work.
  Preserve required portability and defer unrelated packaging or deployment
  work until it can establish something useful.
- For GitHub work, confirm the repository and search existing issues before
  creating one. Read the current body and relevant comments before editing.
  Write a readable title and a self-contained body. Use an action verb matching
  the deliverable, such as investigate, add, validate, or decide. Lead with the
  problem, impact, and desired outcome.
  State investigation questions, needed evidence, relevant version differences,
  and uncertainties. Give implementation and acceptance work observable
  outcomes and reviewable completion.
- Separate confirmed observations, documented capabilities, assumptions, and
  design proposals. Preserve contracts and acceptance requirements. Put
  substantial issue-specific detail in a closed details section with a
  descriptive summary. Keep standing privacy, testing, and authorization
  rules in repository guidance.
- Discover supported native GitHub issue types and set an appropriate type
  following repository conventions when creating an issue. Use the API if the
  connected tool cannot read or set the type. Set it during creation or on the
  same issue afterward. Verify the saved value through an interface that
  exposes it. Report whether a missing
  value reflects lack of repository support, tool limitations, or a specific
  API access or operation failure. A label cannot set a native type.
- Organize stories into reviewable children. Use native parent and blocker
  relationships for actual dependencies where available. Keep overall sequence
  in the parent and avoid duplicate lists and transitive blockers.
- Preserve state, relationships, labels, native issue type, accurate
  requirements, and unrelated metadata when editing. Update the body as
  scope changes. Use comments for supporting evidence.
- Prefer structured arguments for GitHub writes. With a CLI, use a body file
  that preserves actual newlines. Read back saved text and changed
  relationships. Follow existing authorization for creation, edits, and
  closure. Reuse authorization that still applies. Preserve merge and hardware
  acceptance conditions even after local implementation is complete.

## Git workflow

- When staging is authorized, stage explicit paths for the requested work,
  inspect the staged diff, and preserve unrelated staged content.
- A commit message request authorizes drafting alone. Suggest a commit message
  after completed repository changes unless the user requests otherwise. Use the
  agent's supported draft format. In commit bodies, prefer top-level paragraphs.
  Use bullets when they materially improve organization.
- Obtain explicit authorization for direct issue closure through an API,
  connector, CLI, or browser. Local completion and successful checks grant no
  closure permission. An authorized commit resolving an issue may include
  `Fixes #123` for a bug or `Closes #123` for completed behavior or a task
  without separate direct-closure authorization. Pushing and merging require
  their own authorization. Use `Refs #123` for partial work or outstanding
  acceptance and explain why the issue remains open or what remains to be done.

## Privacy and live systems

- Except for the private operator identifiers described below, keep
  credentials, tokens, QR payloads, private addresses and device
  identities, raw captures, databases, and sensitive logs out of tracked
  files, client bundles, diagnostics, issues, and PRs. Treat client-visible
  environment variables as public.
- Private operator diagnostics and installation-local debug logs may carry the
  shade, room, or group identifiers necessary for documented troubleshooting.
  Keep credentials out of those outputs. Review and redact identifying details,
  private addresses, and sensitive raw evidence before any sharing.
- Use fictional fixtures. Keep normal tests independent of private
  configuration, household inventory, VPNs, real credentials, and live
  installations. Use fictional peers for failures and writes.
- Verify repository-local ignore coverage before saving private evidence.
  Preserve useful requested measurements and configuration records. Review
  the whole package before sharing for credentials, stale artifacts, local
  paths, and sensitive evidence. Keep unrelated private project names, links,
  and machine paths out of deliverables. Attribute private references only
  when authorized in an appropriate maintenance record. Retain outputs
  according to purpose and preserve intended deliverables and prior evidence.
- Local builds, tests, exports, and package preparation authorize no device
  changes, deployment, installation, provisioning, publication, uploads,
  signing, or account changes. Before an external write, establish the
  authorized operation, target, and scope. Reuse applicable authorization.
  Determine whether a live operation is read-only from its effects, regardless
  of HTTP method or label. Keep investigations read-only absent explicit change
  authorization. Use a fake to investigate a mutation endpoint.
- Verify the intended service or controller identity before sending
  credentials or writes. An address alone may be insufficient. Preserve
  authentication and protocol integrity, including HTTPS and certificate
  verification by default. The existing configuration option allows the
  operator to opt out of certificate verification only for a self-signed
  Crestron controller.
- Verify the outcome of an uncertain remote write before retrying. Do not
  silently change target, transport, or recovery method. Report the evidence
  actually obtained. Local checks and accepted requests leave remote state and
  physical completion to be verified at the relevant boundary.

## Formatting and validation

- Derive commands, working directories, supported formats, and required
  checks from the project and CI. Use existing formatters, linters, dependency
  managers, lockfiles, and integrity checks where present. Use configuration
  for mechanical rules. Pin newly introduced tools, SDKs, dependencies, and
  build inputs when their first consumer needs them. Avoid introducing moving
  tags, unpinned downloads, and incidental dependency upgrades.
- Format supported changed files, review the diff, and follow with applicable
  checks. Repeat those steps when later edits invalidate them. Use existing
  changed-file commands or explicit paths when unrelated work is present.
  Preserve the Git index. Keep broad formatting passes separately scoped.
  Respect generated output, unsupported formats, private data, caches, and
  deliberate exclusions. Check generator destinations first and preserve
  unrelated outputs, saved configurations, and release evidence.
- From the repository root, install the test dependencies in a Python 3.14.2
  environment with `python -m pip install -r requirements-test.txt`. Run
  `python -m pytest` for Python behavior changes or
  `python -m pytest tests/test_docs_options_flow.py` for the README/Options
  flow contract. CI runs pytest on pull requests and pushes to `main`.
  For a local run of the separate hassfest check, follow the
  [README development setup](README.md#development-setup).
- Choose checks by change and risk. Review prose and formatting for
  documentation-only work, run relevant generators for changed generated
  artifacts, and run applicable builds, behavior tests, and platform checks
  for implementation. Keep configured standard checks in normal validation.
  Report actual outcomes and relevant tool or platform details. Distinguish
  formatting, generation, compilation, test execution, simulated peers,
  packaging, and hardware acceptance. Report blocked or unavailable checks
  as unverified. Local verification alone gives no reason to install system
  tools, change security policy, operate hardware, or deploy.
