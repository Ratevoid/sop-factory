---
name: sop
description: Route project work through the bundled project-neutral deterministic SOP runtime.
---

# SOP Framework Router

Use the plugin root's `scripts/run-sop` launcher as the deterministic evidence layer.

1. For an empty or capability question, run `scripts/run-sop status --json`.
2. Otherwise run `scripts/run-sop directive '<original request>' --json` safely.
3. For project-scoped work, run `scripts/run-sop context --request '<normalized request>' --json`.
4. Search registered recipes with `scripts/run-sop recipe search --request '<request>' --json`.
5. Only execute a unique compatible recipe. Stop on confirmation, no-match, or known contract errors.

Disclose each real SOP call with its action, purpose, risk, result, counters, and one decisive fact.
Read-only checks do not authorize writes. Delete, package, publish, push, permissions, and secrets
remain high risk and require explicit approval for the exact current target. Project knowledge must
come from an injected Profile, Adapter, contract, or runtime fingerprint, never from this package.

When promoting a repeatable operation, follow `references/recipe-policy.md`.
