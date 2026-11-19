# Crestron Home Python API contracts

- Document new or changed reusable APIs and meaningful shared members using
  Python docstrings. Apply the same conventions to existing contracts in
  requested documentation work. Put the authoritative contract on the
  declaration or interface callers use. Keep implementation rationale beside
  the code.
- Inspect analogous declarations in the module and repository. For new kinds
  of declarations without a local precedent, follow Python and Home Assistant
  idioms. Use predictable behavior for related APIs when implementation is
  authorized. A documentation-only change preserves API design and behavior.
- Use consistent terms and structure for equivalent contracts. Repeat a shared
  parameter's meaning where that helps an independent reader. Keep
  corresponding descriptions comparable and make consequential differences
  clear where readers form expectations, including snapshots versus live views.
- State accepted inputs, units, formats, ranges, preconditions, and meaningful
  empty, omitted, null, or sentinel values that types alone cannot express.
  Name parameters, fields, options, and individual callback arguments when that
  connects a description to its subject. Document meaningful members of
  options, results, and enums by explaining their effect on behavior.
- Explain success and failure, including exceptions, rejection, partial or
  unchanged results, fallback, and best-effort behavior. Distinguish request
  acceptance from a confirmed result. Where relevant, describe side effects,
  environment, ownership, lifetime, initialization order, execution context,
  cancellation, and blocking.
- State actual preconditions and guarantees. Avoid implying unimplemented
  validation, thread safety, recovery, or error results. Use a short example
  when it prevents likely misuse. Preserve sound wording and repair deficient
  precedents in proportion to what is missing or misleading. Avoid stylistic
  reflow and broad rewrites of accurate neighboring docs.
- For an evidenced workaround, name the affected version or hardware revision,
  explain the failure avoided, and cite the supporting evidence. Use code to
  enforce runtime contracts and tests to verify them where appropriate. For
  scripts, document paths, prerequisites, exit or exception behavior, and
  file, subprocess, or network effects where needed. Follow native
  documentation conventions without introducing another language's tags or
  a new documentation tool for this alone.
