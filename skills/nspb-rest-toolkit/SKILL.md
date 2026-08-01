---
name: nspb-rest-toolkit
description: Use when the user asks about Oracle EPM Cloud Planning & Budgeting (NSPB/PBCS) -- applications, dimensions, forms, jobs, business rules, migration/LCM snapshots, substitution variables, or planning-unit approvals. Talks directly to Oracle's REST APIs via the nspb-rest-toolkit MCP connector. Read this before calling any destructive tool.
---

# Using nspb-rest-toolkit safely

This skill governs every tool this plugin's MCP connector exposes. Read
section 2 before calling anything destructive, even if the request sounds
unambiguous.

## 1. Reads vs. destructive

Every tool is either a read or a destructive operation, enforced in code:
every destructive call requires an explicit `confirm: true` argument, or it
raises an error before any network request is made. Reads (list
applications, list dimensions, read form data, get job status, get
migration status, etc.) are always safe to call freely to gather context.

## 2. The confirm rule -- read this even if you think you already know it

**Never call a destructive tool with `confirm=true` on the same turn as the
user's first request, regardless of phrasing.**

This applies even to phrasing that sounds imperative and complete, such as
"Run the CalcAll rule on Vision", "Import the March actuals file", "Clear
the FY25 budget data slice", or "Promote this planning unit". None of these
are confirmation -- they are the *request*. Always:

1. Call whatever read-only tools you need to understand exactly what the
   destructive action will do.
2. Describe that to the user in plain language: what will run, what will
   change, and the before/after if knowable.
3. Wait for the user's next message to contain explicit confirmation.
4. Only then call the destructive tool again, this time with
   `confirm=true`.

If the user's first message already says "and don't ask me to confirm" --
still restate what will happen and wait for their next message, unless a
standing, specifically-scoped authorization already covers this exact
action.

## 3. Form writes: never guess the grid shape

Before ever calling `write_form_data`, call `read_form_grid_shape` (or
`read_form_data`) for the target form/plantype in the **same
conversation** -- not from a remembered shape, even from earlier this
session. Build the write body from what that call actually returned. Same
for `clear_data_slice` / `export_data_slice` / `export_data` -- the
`grid_definition`/`query_definition` shape should come from a real prior
read.

## 4. Job types

`submit_job` accepts any `jobType` string. Most are destructive; a handful
are read-only (`EXPORT_DATA`, `EXPORT_METADATA`, `EXPORT_SECURITY`,
`EXPORT_AUDIT`, `EXPORT_JOB_CONSOLE`, `EXPORT_CELL_LEVEL_SECURITY`,
`EXPORT_VALID_INTERSECTIONS`, `EXPORT_LIBRARY_DOCUMENTS`). An unrecognized
`jobType` is treated as destructive by default (fail closed). Note: the
confirmed job type names are `CUBE_REFRESH` and `CLEAR_CUBE`, not
`REFRESH_DATABASE` or `CLEAR_DATA`.

## 5. Migration/LCM jobs use a different status contract

Planning jobs use named states (`Completed` / `Error` / `Invalid`).
Migration/LCM jobs use numeric states (`-1` in progress, `0` success, `1`
completed with issues). A `1` is a **valid terminal state**, not a failure
-- call `get_migration_job_task_details` to see what actually happened
before telling the user the operation failed.

## 6. Connections

Most installs of this plugin have exactly **one** connection, always named
`default` -- pass `connection: "default"` on every tool call unless
`list_connections` shows something different (a multi-tenant
`connections.yaml` may be configured instead, in which case call
`list_connections` first and confirm which customer/tenant an action
targets before running anything destructive).

## 7. Auth failures -- what to tell the user, never what to ask them for

**Never ask a user to paste a password, API key, or token into chat so you
can pass it through.** Credentials are resolved by the server process
itself from its own environment/config, set once when the user installed
this plugin -- your job is to report *that* authentication failed and
*why*, and point at the right out-of-band fix:

- `basic` 401/403: credentials or role assignment on the tenant are the
  likely cause -- tell the user, don't retry blindly.
- `oauth2` auth error mentioning an expired/missing/already-consumed token:
  the user needs to re-run the one-time interactive Device Code bootstrap
  themselves (`python -m nspb_rest_toolkit.oauth2_bootstrap`) -- this needs
  a real browser and a real login, you cannot do it for them.
- `oauth2` error with `error_description="Token Audience"` even right after
  a successful bootstrap: a tenant-side IDCS setup gap (missing "secondary
  audience" on the app registration), not a credentials problem -- don't
  retry the bootstrap hoping it self-resolves.
- `bearer_token` 401: the token has almost certainly expired -- a human
  needs to regenerate it from their Oracle Identity Domain console and
  update the plugin's configuration.
