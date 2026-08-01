# Using nspb-rest-toolkit safely

This document is for whatever LLM is calling this toolkit's tools (via MCP,
the OpenAPI server, or the Open WebUI Tool) -- not just for the humans
integrating it. If you are a model with these tools available, read this
before calling anything destructive.

## 1. Reads vs. destructive

Every operation in this toolkit is tagged `read` or `destructive` in
[docs/endpoint-inventory.md](endpoint-inventory.md). The tag is enforced in
code, not just documentation: every destructive call requires an explicit
`confirm: true` (or `confirm=True`) argument. Without it, the call raises
`EPMConfirmationRequiredError` before any network request is made.

Reads are always safe to call with no gating -- list applications, list
dimensions, read form data, get job status, get migration status, etc. Call
them freely to gather context.

## 2. The confirm rule -- read this even if you think you already know it

**Never call a destructive tool with `confirm=true` on the same turn as the
user's first request, regardless of phrasing.**

This applies even to phrasing that sounds imperative and complete, such as:
- "Run the CalcAll rule on Vision"
- "Import the March actuals file"
- "Clear the FY25 budget data slice"
- "Promote this planning unit"

None of these are confirmation. They are the *request*. The correct
sequence is always:

1. Call whatever read-only tools you need to understand exactly what the
   destructive action will do (which rule, which cells, which file, which
   plan type, which planning unit and its current status).
2. Describe that to the user in plain language: what will run, what data
   or metadata will change, and (if knowable) what the before/after looks
   like.
3. Wait for the user's next message to contain explicit confirmation
   ("yes", "go ahead", "do it", etc.).
4. Only then call the destructive tool again, this time with
   `confirm=true`.

If a user's first message already anticipates this and says something like
"run rule X and don't ask me to confirm" -- still don't skip the
confirmation step within that same turn. Restate what will happen and wait
for their next message. The one exception: if the user has set up a
standing instruction (e.g. in a system prompt or repeated project
convention) that explicitly authorizes a *specific, scoped* action without
per-call confirmation, and you are confident that authorization actually
covers the action in front of you -- otherwise, always ask.

## 3. Form writes: never guess the grid shape

Oracle's REST API does **not** have a symmetric form-ID-scoped read/write
pair (see endpoint-inventory.md section 5 for the full gap analysis). The
write path (`write_form_data` / Import Data Slice) is **plan-type-scoped**,
and its body must match the real POV/row/column shape of the data you're
writing into.

Before ever calling `write_form_data`:
1. Call `read_form_grid_shape` (or `read_form_data`) for the target
   form/plantype, in the **same conversation**. This is not optional and
   not something you can skip because you inspected this form in a
   previous session -- forms change, and a stale remembered shape will
   either fail or, worse, write to the wrong cells.
2. Build the write body from what that call actually returned, not from
   what you expect a "typical" Planning form to look like.
3. Only then call `write_form_data` (and only with `confirm=true` after
   the confirmation step in section 2).

The same applies to `clear_data_slice` and `export_data_slice` /
`export_data` -- the `grid_definition`/`query_definition` shape should come
from a real prior read, not from guesswork.

## 4. Job types

`submit_job` accepts any `jobType` string. Most are destructive (business
rules, data/metadata import, cube refresh/restructure, security import,
etc.) -- a handful are read-only (`EXPORT_DATA`, `EXPORT_METADATA`,
`EXPORT_SECURITY`, `EXPORT_AUDIT`, `EXPORT_JOB_CONSOLE`,
`EXPORT_CELL_LEVEL_SECURITY`, `EXPORT_VALID_INTERSECTIONS`,
`EXPORT_LIBRARY_DOCUMENTS`). See `endpoints/jobs.py`'s `JOB_TYPE_TAGS` for
the full, authoritative list. An unrecognized `jobType` is treated as
destructive by default (fail closed).

Note: the confirmed current job type names are `CUBE_REFRESH` and
`CLEAR_CUBE` -- not `REFRESH_DATABASE` or `CLEAR_DATA` as you might expect
from older documentation or convention. Use the exact strings from
`JOB_TYPE_TAGS`.

## 5. Migration/LCM jobs use a different status contract

Planning jobs use named states (`Completed` / `Error` / `Invalid`).
Migration/LCM jobs use numeric states (`-1` in progress, `0` success, `1`
completed with issues). A `1` is a **valid terminal state**, not a failure
-- if you see it, call `get_migration_job_task_details` to see what
actually happened before telling the user the operation failed.

## 6. Auth methods: basic, oauth2, bearer_token -- the safety model doesn't change

A connection's `auth_method` (set in `connections.yaml`, not something you
choose or pass per-call) is `basic`, `oauth2`, or `bearer_token`. This is
entirely about how the toolkit authenticates to Oracle -- it has **no
effect** on the safety rules above. Reads are still always safe; destructive
operations still always require `confirm=true`; you still never skip the
"describe, then wait for confirmation" sequence in section 2. Don't let the
auth method in play change how carefully you treat a destructive call.

What differs per method, for your own troubleshooting context:

- `basic`: username/password, resolved server-side. If a call fails with a
  401/403, the credentials or the account's role assignment on that tenant
  are the likely cause -- tell the user, don't retry blindly.
- `oauth2`: Oracle's user-context Device Code + Refresh Token flow (MFA
  tenants require this; there's no client-credentials/machine-to-machine
  option for EPM Cloud). It requires a one-time, human-in-the-browser
  bootstrap (`python -m nspb_rest_toolkit.oauth2_bootstrap`) run by the
  operator outside of any chat session -- you cannot do this step yourself,
  it needs a real browser and a real login. Refresh after that is
  unattended, unless the connection is configured with `allow_refresh:
  false` (session-only access), in which case there's no refresh at all and
  the operator re-runs the bootstrap by hand each time the access token
  expires. If a call fails with an auth error whose message says the refresh
  token is expired/already consumed, or (for `allow_refresh: false`
  connections) that the cached token is missing/expired, tell the user to
  re-run the bootstrap command -- not something you can fix by retrying or
  by asking for a password. If instead every call 401s with
  `error_description="Token Audience"` even right after a successful
  bootstrap, that's a tenant-side IDCS setup gap (missing "secondary
  audience" on the app registration -- see README.md's oauth2 section), not
  a toolkit bug or a credentials problem -- don't retry the bootstrap
  repeatedly hoping it self-resolves.
- `bearer_token`: a single static, pre-obtained token with no refresh path.
  If it 401s, the token has almost certainly expired and a human needs to
  regenerate it from their Oracle Identity Domain console and update the
  stored credential -- again, not something to retry your way out of.

In all three cases: never ask a user to paste a raw token, password, or
refresh token into chat (see section 7) -- your job is to report *that*
authentication failed and *why* the error message says it failed, and point
at the right out-of-band fix (re-check credentials, re-run bootstrap,
regenerate token), not to try to obtain or relay the secret yourself.

## 7. Credentials

Never ask a user to paste a password, API key, or token into chat so you
can pass it through. Credentials are resolved server-side from environment
variables or an OS secrets store via `credential_ref` in `connections.yaml`
-- your job is to pass a `connection` slug, never a raw secret.

## 8. Multi-tenant awareness

Every tool takes a `connection` argument (a slug from `connections.yaml`).
Call `list_connections` first if you're not sure which connections are
configured, and always confirm which customer/tenant an action targets
before running anything destructive -- especially in a session where
multiple connections are configured, mixing them up has real consequences.
