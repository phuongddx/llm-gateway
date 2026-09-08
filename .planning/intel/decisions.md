# Decisions Intel (ingest 2026-09-08)

No documents were classified ADR (0 of 26). Per taxonomy, only ADR-classified
sources produce decision entries, and no source carries `locked: true`.
**Decisions locked: 0.**

Decision-grade content extracted from non-ADR sources lives elsewhere by type:

- User-locked design decisions from the Approved z.ai Coding Plan spec
  (Max tier · coding endpoint with ToS risk accepted · all GLM → coding with
  **no fallback** · credit estimation in analytics) are recorded as protocol
  constraints in `constraints.md` (entries sourced to
  `docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md`).
- Historical "Key Decisions" from the three completed plan sets
  (0416 gateway-features, 0417 playground-web-ui, 0419 manifest-cutover) are
  recorded as context in `context.md` under "Architecture evolution" and
  per-plan-set topics. They are implemented history, not standing decision
  records, and carry no lock.
