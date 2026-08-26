---
name: learning-closeout
description: Run the mandatory learning closeout after corrections, preventable mistakes, rework, failed routes, rollback, incidents, or verified better methods.
---

# Learning Closeout

Use this skill as a final-response gate. It does not replace requested work or expand permission for external actions.

## Trigger Audit

Run the closeout when the task includes a user correction, an agent-caused mistake or omission,
retry or reroute, rollback, security or remote-write incident, disproved assumption, or verified
better method. The user must not need to request it.

## Learning Decision

1. Record the incident or route change in the governed diary.
2. Assess mechanism-level facts separately from reusable control-level rules.
3. Require current evidence; do not persist guesses, logs, secrets, temporary state, or ordinary progress.
4. Search the governed memory narrowly for three to five same-scope results.
5. Deduplicate each verified reusable lesson before writing one semantic conclusion per lesson item.
6. Read back every new item and run a narrow recall query that finds it.
7. If no durable lesson qualifies, write `LESSON_DECISION:none|trigger=<signal>|reason=<specific boundary>|evidence=<checked evidence>` to the diary.

Use only the configured governed public MemPalace MCP and its active governance policy. If it is
unavailable, report that once and continue the main task without bypassing the guard.

## Completion Gate

Do not send the final response until the final diary status is written and every qualifying lesson
has passed deduplication, write, readback, and recall testing, or every trigger has an evidence-backed
structured no-lesson decision. Briefly report what was persisted or why nothing qualified.
