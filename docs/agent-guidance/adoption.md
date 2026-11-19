# Guidance adoption record

Read this maintenance record when asked to adopt or refresh guidance,
including guidance for a new language or technology. It is not required
reading during routine development and is not active agent guidance.

- Source library: `C:\dev\agent-guidance` ([tunnelvisionlabs/agent-guidance](https://github.com/tunnelvisionlabs/agent-guidance))
- Source revision: `6812463e73e007f5ab2e670b8df9942e9cc33a05`. The source working tree was clean.
  Local `main` was one commit ahead of its `origin/main` tracking ref.
- Adopted or refreshed on: 2026-11-19
- Destination instructions: [root guide](../../AGENTS.md),
  [integration API guide](../../custom_components/crestron_home/AGENTS.md), and
  [test guide](../../tests/AGENTS.md). The local hassfest procedure remains in
  the [README development setup](../../README.md#development-setup).

## Selected modules

| Module ID | Source path | Agreed scope and destination | Local adaptations and reasons |
| --- | --- | --- | --- |
| `shared.defaults` | `guidance/shared/defaults.md` | Shared, root `AGENTS.md` | Use the integration, blueprint, documentation, and test paths and the project's actual tooling. |
| `shared.documentation` | `guidance/shared/documentation.md` | Shared, root `AGENTS.md` | Retain the existing README entry point and the Options guide's diagram and task-specific prose. The existing documentation contract test stays as written. |
| `shared.documentation-lifecycle` | `guidance/shared/documentation-lifecycle.md` | Shared, root `AGENTS.md` | Use code, UI strings, and maintained usage docs for current behavior, GitHub Issues for detailed planned work, and Git/PR history for earlier states. Preserve the README milestone material during adoption. |
| `shared.sensitive-data` | `guidance/shared/sensitive-data.md` | Shared, root `AGENTS.md` | Preserve repository-local evidence and pre-sharing redaction rules. The operator-only exception and existing output gaps are documented below. |
| `shared.live-system-access` | `guidance/shared/live-system-access.md` | Shared, root `AGENTS.md` | Apply boundaries to Home Assistant, real controllers, and physical shade movement. Preserve the documented operator opt-out for self-signed certificates, with verification on by default. |
| `shared.api-contracts` | `guidance/shared/api-contracts.md` | Shared, `custom_components/crestron_home/AGENTS.md`, with a root read trigger | Use Python docstrings for reusable contracts and meaningful shared members. Retain coverage and authoring guidance for touched APIs even without a docstring check. Existing docstrings were left in place. |
| `strategies.behavior-testing` | `guidance/strategies/behavior-testing.md` | Shared, `tests/AGENTS.md`, with a root read trigger | Use observable production behavior and faithful boundary fakes. Preserve the existing tests, including the documentation smoke check. |
| `languages.home-assistant-testing` | `guidance/languages/home-assistant-testing.md` | Shared, `tests/AGENTS.md`, with a root read trigger | Apply framework fixture, async timing, ownership, and evidence rules to the Crestron HTTPS boundary. Preserve the existing suite's lightweight stubs and require evidence for adding isolation. |
| `strategies.incremental-delivery` | `guidance/strategies/incremental-delivery.md` | Shared, root `AGENTS.md` | Preserve the project's milestone-sized work and align regression coverage with the change it protects. Select development and deployment platforms based on the work. |
| `strategies.github-planning` | `guidance/strategies/github-planning.md` | Shared, root `AGENTS.md` | The manifest links the issue tracker, and issues such as [#27](https://github.com/sharwell/ha-crestron-home/issues/27), [#32](https://github.com/sharwell/ha-crestron-home/issues/32), and [#39](https://github.com/sharwell/ha-crestron-home/issues/39) carry detailed outcomes, acceptance criteria, and test plans. Follow the existing authorization boundaries. |
| `strategies.reproducible-verification` | `guidance/strategies/reproducible-verification.md` | Shared, root `AGENTS.md` and README development setup | Use repository-root pytest and the existing hassfest workflow. Correct the README's sibling checkout path and state the Core Python prerequisites. Preserve the current CI workflow and apply pinning to new inputs. |
| `personal.git` | `guidance/personal/git.md` | Split at the user's direction. Existing personal instructions in `~/.codex/AGENTS.md` and this adoption request. Additional rules shared in root `AGENTS.md`. | Retain equivalent personal authorization, staging defaults, commit-message construction and verification, and existing message conventions unchanged. Share explicit-path staging with staged-diff review, draft-only message requests and the default of suggesting a message, direct issue closure and acceptance rules, and the preference for paragraphs in commit bodies. |
| `personal.writing` | `guidance/personal/writing.md` | Shared by user choice, root `AGENTS.md` | Merge prose and review preferences with shared documentation guidance. Keep PR titles distinct from commit-subject requirements. |

## Selected skills

No skill was installed. The source adoption skill was used for this task.
There was no established recurring adoption or documentation-only API review
workflow in this repository to justify copying `adopt-guidance` or `docpass`.

## Relevant omissions and decisions

- **Private diagnostics and logging.** The source keeps private device identities
  out of diagnostics and sensitive logs. The user chose to document a narrow
  exception for identifiers necessary for private operator troubleshooting and
  requested a follow-up review. The README describes per-shade and group
  troubleshooting, `diagnostics.py` exports names and IDs, and
  [#30](https://github.com/sharwell/ha-crestron-home/issues/30) and
  [#32](https://github.com/sharwell/ha-crestron-home/issues/32) specify local
  diagnostics and debug logging needs. The exception covers neither credentials
  nor publication of private details. The existing REST client's debug output
  can also include controller URLs and shade-write payloads. This adoption
  leaves runtime output intact and records those gaps for inventory and
  verification in [#43](https://github.com/sharwell/ha-crestron-home/issues/43).
- **Certificate policy.** The README and both UI string files limit the
  existing verification opt-out to a self-signed controller.
  `DEFAULT_VERIFY_SSL` is true. The guide preserves that user choice and
  still requires confirming the intended controller identity.
- **Testing and enforcement.** `test_assisted_calibration.py`,
  `test_config_flow.py`, and `test_write.py` use lightweight Home Assistant
  substitutes. Keep them runnable for existing coverage. Prefer real Home
  Assistant fixtures for framework behavior in new or revised coverage and
  require concrete evidence for new isolation. This adoption does not
  mandate a harness migration. The source's Bluetooth/GATT, proxy-slot, and
  firmware examples do not apply to this HTTPS integration. The equivalent
  transport, timing, and acceptance distinctions are included.
- **CI and formatting.** The configured hassfest workflow uses
  `actions/checkout@v4` and `home-assistant/actions/hassfest@master`.
  The adoption preserves those existing refs. The hassfest action is intended
  to track the beta release channel. There is no checked-in Python
  formatter, dependency lock, pytest job, or docstring gate. File-local
  Ruff suppressions establish no repo-wide configuration. The guide
  retains the applicable testing and documentation policy without asserting
  automated enforcement or adding tools.
  [Home Assistant hassfest documentation](https://contributors.home-assistant.io/blog/2020/04/16/hassfest/)
- **Language and platform scope.** The source's C#, .NET XML, C, and
  TypeScript documentation conventions do not apply to the Python
  integration, JSON metadata, or YAML blueprint. The Windows recovery
  module requires an Application Control rejection of a locally built test
  executable from current work. A Windows checkout and existing Python
  tests do not meet that condition.

## Verification and limitations

- Reviewed the applicable personal instructions, tracked files, available
  local history, manifest, CI workflow, tests, and relevant GitHub issues.
  No prior repository agent guide or adoption record was found in the
  checkout or available Git history.
- Compared each selected source module with its destination, including
  authorization gates, conditional rules, exceptions, and meaningful
  distinctions. Checked that the active local read triggers resolve and
  that active guidance depends on neither this record nor the source
  checkout.
- Checked Markdown links in the new guidance and README development section,
  whitespace, the README example's Bash syntax, and the integration target.
  Both existing Options documentation assertions passed under Python 3.12.14
  when called directly. Full pytest and hassfest execution were outside the
  documentation checks. The available Python lacked the test dependencies,
  and there was no prepared sibling Core checkout.
- Read back [#43](https://github.com/sharwell/ha-crestron-home/issues/43) to verify
  its saved body and open state. Verified its native `Task` type through the
  GitHub API.
- Compared the Git index before and after adoption. Its contents were identical.
