# Oracle EPM Cloud REST API Endpoint Inventory — Planning & Budgeting Cloud (NSPB)

> Source-grounded inventory compiled by crawling Oracle's official documentation at
> `docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/` on 2026-08-01.
> Every row below traces to text actually fetched from an Oracle doc page during this session. Where a
> detail could not be confirmed from fetched text, it is explicitly flagged rather than guessed.

## 1. API Versions (confirmed)

| API family | Base path | Current version confirmed | Source |
|---|---|---|---|
| Planning REST API | `/HyperionPlanning/rest/{api_version}/...` | **v3** (v2 exists as a predecessor/still-active version) | [`get_information_about_a_specific_rest_api_version_for_planning.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_information_about_a_specific_rest_api_version_for_planning.html) — resource `GET /HyperionPlanning/rest/{api_version}` returns version metadata; example response shows `v3` with `isLatest: true` and `v2` as predecessor. |
| Migration / LCM REST API | `/interop/rest/{api_version}/...` | Mixed **v2** (majority of Migration/LCM operations) with **v3** available for a subset of newer operations (e.g., Delete Files v3, Copy from/to Object Store v3) | [`get_rest_api_versions_for_lcm.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_rest_api_versions_for_lcm.html) — resource `GET /interop/rest/` returns an `items` array of version objects with `lifecycle` (`active`/`deprecated`) and `latest` flags; and the full operations TOC (`all_rest_apis_table.html`) which lists both `_v2` and `_v3` suffixed page variants for several LCM operations, with v1 (unsuffixed) pages retained under a "First Generation REST APIs" heading. |
| Data Integration / Data Management REST API | `/aif/rest/{api_version}/jobs` | **V1** (as printed in fetched examples; not a semantic-versioned family like Planning) | [`fdmee_run_pipeline.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/fdmee_run_pipeline.html), [`fdmee_run_data_rule.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/fdmee_run_data_rule.html) |

**Caveat:** The dedicated "Compatibility Table" page referenced in the task brief
(`compatibility_table_rest_apis.html`) returned **HTTP 404** at both the
`enterprise-performance-management-common/prest/` and `epm-cloud/prest/` mirror paths during this session — it
may have been renamed, merged into `versioning.html`, or is temporarily unavailable. The version findings
above come from the `versioning.html` page and the individual "Get API Versions" operation pages instead,
which are live and current as of the fetch. Versioning is per-API-family and mandatory in every request URL;
version identifiers are case-sensitive (`v3` is valid, `V3` is not) — per [`versioning.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/versioning.html).

## 2. Authentication — OAuth2 Flow (confirmed, with an important correction)

**Correction to the task brief's assumption:** the fetched authentication page does **not** document a
client-credentials grant. Oracle Cloud EPM enforces role-based access control that requires the access token
to carry **user context**, so Oracle explicitly documents the **Device Authorization (Device Code) Grant**
(plus Authorization Code, Resource Owner Password, and Assertion grants as user-context alternatives) —
not Client Credentials — for unattended/scripted access. Source:
[`authentication_oath.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/authentication_oath.html).

> "Oracle Fusion Cloud Enterprise Performance Management uses a role-based access control mechanism to permit
> only authorized users access to the service... This requires that any OAuth 2 access token used to access
> Cloud EPM REST APIs contains a user context."

- **Token endpoint pattern:** `POST https://<tenant-base-url>/oauth2/v1/token`, where `<tenant-base-url>` is
  of the form `idcs-<alphanumericvalue>.identity.oraclecloud.com`.
- **Device code request (step 1):** `POST https://<tenant-base-url>/oauth2/v1/device` with
  `response_type=device_code`, `scope=urn:opc:serviceInstanceID=<SERVICE_INSTANCE_ID>urn:opc:resource:consumer::all offline_access`,
  `client_id=<CLIENT_ID>`.
- **Refresh token exchange (automated/unattended re-auth):** `POST https://<tenant-base-url>/oauth2/v1/token`
  with `grant_type=refresh_token`, `client_id=<DECRYPTED_CLIENT_ID>`, `refresh_token=<DECRYPTED_REFRESH_TOKEN>`.
  No `client_secret` is documented for this public-client flow.
- **Presenting the token on API calls:** header `Authorization: Bearer <access_token>` on every subsequent
  REST call, e.g. `Authorization: Bearer eyJ5M4Q...`.
- **Expiry/refresh behavior:**
  - Access token `expires_in`: `3600` seconds (1 hour).
  - Refresh tokens expire after **7 days**; Oracle's own guidance for long-running unattended scripts is to
    run a scheduled job that refreshes the refresh token every 6 days to avoid lapsing.
  - An expired refresh token returns HTTP 400 with `{"error":"invalid_grant","error_description":"Token is expired for client : <CLIENT_ID>"}`.
  - A refresh token already used returns `{"error":"invalid_grant","error_description":"The token has already been consumed"}` (refresh tokens are single-use/rotating).

**Implication for the toolkit:** because there is no client-credentials path, a user-context OAuth2 flow is
required for MFA-enforcing tenants — the Device Code flow for interactive first-auth plus the Refresh Token
flow for unattended reuse. **This is implemented** (`src/nspb_rest_toolkit/oauth2.py` + the
`oauth2_bootstrap` CLI; `auth_method: oauth2` in `connections.yaml`) — see [README.md](../README.md#oauth2)
for setup and [docs/SKILL.md](SKILL.md) section 6 for the operational/troubleshooting summary. Basic Auth
(username/password) is also still shown working in some fetched cURL examples and remains fully supported as
`auth_method: basic` for tenants that don't enforce MFA; a static pre-obtained Bearer token
(`auth_method: bearer_token`) is a third, lower-effort option for manual/short-lived use.

This flow is now implemented (`auth_method: oauth2` — see `src/nspb_rest_toolkit/oauth2.py`): an interactive
one-time Device Code bootstrap (`python -m nspb_rest_toolkit.oauth2_bootstrap`) writes the initial
access+refresh token pair to a per-connection on-disk cache, and `EPMClient` refreshes unattended from there
via the Refresh Token grant, persisting Oracle's rotated refresh token immediately after every exchange since
it's single-use. A third `auth_method: bearer_token` is also available for a single pre-obtained static token
with no refresh logic. Basic Auth remains fully supported and unchanged.

## 3. Applications

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| GET | `/HyperionPlanning/rest/{api_version}/applications` | List applications the calling user is assigned to, with key app metadata (type, theme, storage type, appType, hybrid flag, etc.). Requires Service Administrator role. | read |
| GET | `/HyperionPlanning/rest/v3/applications/{application}/summary` | Return an AI/automation-oriented markdown-ish summary of an application's structure (dimensions, hierarchy depth, etc.); Oracle notes this response shape may change between releases and isn't meant for stable long-term parsing. | read |

Source: [`get_applications.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_applications.html), [`get_applications_summary.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_applications_summary.html). No dedicated "get single application by name" resource distinct from the list/summary calls was found in fetched pages.

## 4. Dimensions / Members

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| GET | `/HyperionPlanning/rest/v3/applications/{application}/plantypes` | List plan types (cubes) for an application. | read |
| GET | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/dimensions` | List dimensions associated with a plan type (supports `q` filter, paging, `fields`). | read |
| GET | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/dimensions/{dimname}` | Get a dimension's hierarchy/details, including hidden and attribute dimensions, with alias-table and field selection support. | read |
| GET | `/HyperionPlanning/rest/{api_version}/applications/{application}/dimensions/{dimname}/members/{member}` | Get a single member's properties (parent, data storage, data type, two-pass calc flag, etc.). Requires Service Administrator role. | read |
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/dimensions/{dimname}/members` | Add a new member under a specified parent in a dimension outline (payload: `memberName`, `parentName`). Parent must be enabled for dynamic children and cube-refreshed beforehand. Requires Service Administrator role. | destructive |

Source: [`get_plan_types.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_plan_types.html), [`get_dim_plan_types.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_dim_plan_types.html), [`get_dim_details.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_dim_details.html), [`get_member.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_member.html), [`add_member.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/add_member.html). No dedicated "edit/update member" or "delete member" REST resource was found in the fetched TOC (`add_member.html` is add-only); member edits beyond add appear to route through the `IMPORT_METADATA` job type (see Jobs — Typed, below) rather than a per-member PATCH/PUT endpoint.

## 5. Forms

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| GET | `/HyperionPlanning/rest/v3/applications/{application}/forms/{idorname}/data` | "Export Form Data" — return a JSON data grid (pov, rows, columns) for the slice defined by a specified Planning form; supports `pageMbrList`, `displayMemberAs`, `forceStartExpanded`, `filterMembers`, `fields` query params. Oracle's own guidance: call once with `fields=gridInfo,pov` to discover grid shape, then a second call for row/column data. | read |
| POST | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/exportdataslice` | "Export Data Slice" — export a JSON data grid for an arbitrary region defined by a `gridDefinition` (not tied to a specific form ID); only cells the user has read access to are returned. | read |
| POST | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/importdataslice` | "Import Data Slice" — write a JSON data grid (pov/columns/rows) into a plan type; supports `aggregateEssbaseData` (add vs. overwrite), `cellNotesOption`, `dateFormat`, rejected-cell reporting. This is the write-side counterpart used for form-shaped data, but it is **plan-type-scoped, not form-ID-scoped**. | destructive |
| POST | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/exportdata` | "Export Data" — export data via an axis-based query definition (`PovAxisDefinition`/`ColumnAxisDefinition`/`RowAxisDefinition`), with options for supporting detail/cell notes and percent formatting. | read |
| POST | `/HyperionPlanning/rest/v3/applications/{application}/plantypes/{plantype}/cleardataslice` | "Clear Data Slice" — clear Planning/Essbase data for a region defined by `gridDefinition`; `clearEssbaseData` and `clearPlanningData` flags control scope. | destructive |

**Gap versus the task brief's assumption:** the brief anticipated a symmetric pair of endpoints
`POST .../forms/{form}/data` (read) and `PATCH .../forms/{form}/data` (write). The fetched docs do **not**
show that shape. What's actually documented is (a) a **GET**-based, form-ID-scoped **read** endpoint
("Export Form Data"), and (b) a **plan-type-scoped** (not form-ID-scoped) **write** endpoint ("Import Data
Slice") plus a separate generic axis-query export ("Export Data"/"Export Data Slice"). There is no
`get_form.html`/"get form definition" (structure-only, no data) page in the crawled TOC, and no
`import_form_data.html`/PATCH-based form-scoped write page — targeted searches for both came up empty. Treat
the write path as confirmed only at the plan-type grid level, not at the individual-form level, unless a page
search under a name not yet tried turns one up.

Sources: [`get_export_form_data.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_export_form_data.html), [`export_dataslices.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/export_dataslices.html), [`import_dataslices.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/import_dataslices.html), [`export_data_ia.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/export_data_ia.html), [`clear_dataslices.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/clear_dataslices.html).

## 6. Jobs — Generic (submit / status)

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/jobs` | Execute a job of any supported `jobType` (payload: `jobType`, `jobName`, `parameters`). Generic envelope for all typed jobs listed in section 7. | destructive (submission call itself is a POST that can trigger mutating or read-only jobs — see section 7 for per-jobType tag) |
| GET | `/HyperionPlanning/rest/{api_version}/applications/{application}/jobs/{jobIdentifier}` | "Retrieve Job Status" — poll processing state (`status` code, `descriptiveStatus`, `details`, `detailedStatus`) for a submitted job by ID. | read |
| — | `retrieve_job_status_details.html`, `retrieve_child_job_status_details.html` (titles confirmed via TOC; full method/path not independently re-fetched this session) | Retrieve more granular status detail / child-job status for multi-step jobs (e.g., batch rule sets). | read |
| GET | `/HyperionPlanning/rest/{api_version}/applications/{application}` (job-definitions variant) | "Get Job Definitions" — list predefined job definitions available to execute (title confirmed via TOC at `get_job_definitions.html`; exact path segment not independently re-fetched this session — do not treat the path shown here as fully confirmed). | read |

Response envelope common to job status calls (confirmed): `status` (`-1` in progress, `0` success, `1`
error, `2` cancel pending, `3` cancelled, `4` invalid parameter, `Integer.MAX_VALUE` unknown), `details`,
`jobId`/`jobID`, `jobName`, `descriptiveStatus`.

Source: [`execute_a_job.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/execute_a_job.html), [`retrieve_job_status.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/retrieve_job_status.html).

## 7. Jobs — Typed Job Types (`jobType` values for `POST .../applications/{application}/jobs`)

All rows below share the same submission resource `POST /HyperionPlanning/rest/{api_version}/applications/{application}/jobs` with body `{"jobType": "<value>", "jobName": "...", "parameters": {...}}`. Source for the full jobType enumeration: [`execute_a_job.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/execute_a_job.html) (per-jobType `parameters` schemas were not individually itemized on the fetched page beyond the generic envelope, except where noted).

| jobType | Purpose | Tag |
|---|---|---|
| `RULES` | Launch a business rule (`jobName` = exact rule name; optional runtime prompt parameters). | destructive |
| `RULESET` | Launch a business ruleset. | destructive |
| `PLAN_TYPE_MAP` | Copy data between block-storage and aggregate-storage cubes (or between two cubes). | destructive |
| `IMPORT_DATA` | Import data from a file in the Planning repository into the application. | destructive |
| `EXPORT_DATA` | Export application data to a file stored in the repository. | read |
| `IMPORT_METADATA` | Import metadata (dimensions/members) from a repository file into the application. | destructive |
| `EXPORT_METADATA` | Export metadata to a file stored in the Planning repository. | read |
| `CUBE_REFRESH` | Refresh the Planning application cube (this is Oracle's current jobType name for what the task brief called `REFRESH_DATABASE` — no separate `REFRESH_DATABASE` string was found in the fetched enumeration; `CUBE_REFRESH` is the confirmed current value). | destructive |
| `CLEAR_CUBE` | Clear specific data within input/reporting cubes (this is the confirmed current jobType for what the brief called `CLEAR_DATA`; no bare `CLEAR_DATA` string appears in the fetched enumeration — `CLEAR_CUBE` is what's documented). | destructive |
| `ADMINISTRATION_MODE` | Toggle/administer application administration-mode operations. | destructive |
| `COMPACT_CUBE` | Compact the outline file of an ASO cube. | destructive |
| `RESTRUCTURE_CUBE` | Full restructure of a BSO cube to reduce fragmentation. | destructive |
| `MERGE_DATA_SLICES` | Merge incremental data slices of an ASO cube. | destructive |
| `OPTIMIZE_AGGREGATION` | Improve ASO cube aggregation performance. | destructive |
| `IMPORT_SECURITY` | Import access-control-list (security) records from a CSV file in the repository; params include `fileName`, `clearAll`, `errorFile`. | destructive |
| `EXPORT_SECURITY` | Export ACL/security records to a CSV file. | read |
| `EXPORT_AUDIT` | Export audit records for a date range. | read |
| `EXPORT_JOB_CONSOLE` | Export Job Console records to CSV. | read |
| `SORT_MEMBERS` | Sort dimension members of a business process. | destructive |
| `IMPORT_EXCHANGE_RATES` | Import exchange rates into the application. | destructive |
| `AUTO_PREDICT` | Schedule Auto Predict predictions. | destructive |
| `IMPORT_CELL_LEVEL_SECURITY` | Import cell-level security from a ZIP file. | destructive |
| `EXPORT_CELL_LEVEL_SECURITY` | Export cell-level security to a ZIP file. | read |
| `IMPORT_VALID_INTERSECTIONS` | Import valid-intersection rules from a ZIP file. | destructive |
| `EXPORT_VALID_INTERSECTIONS` | Export valid-intersection groups. | read |
| `REPORT_BURSTING` | Execute report/book bursting. | destructive |
| `EXPORT_LIBRARY_DOCUMENTS` | Export documents from the Planning library. | read |
| `IMPORT_LIBRARY_DOCUMENTS` | Import documents into the Planning library. | destructive |
| `DELETE_LIBRARY_DOCUMENTS` | Delete documents from the Planning library. | destructive |
| `CONFIGURE_OGL_SERVER` | Update the Oracle Guided Learning server URL/app ID. | destructive |

**Note on the task brief's expected literal strings:** `RULES`, `IMPORT_DATA`, `EXPORT_DATA`,
`IMPORT_METADATA`, `EXPORT_METADATA` all matched exactly. `CLEAR_DATA` and `REFRESH_DATABASE` did **not**
appear verbatim in the fetched jobType enumeration — the current documented equivalents are `CLEAR_CUBE` and
`CUBE_REFRESH` respectively. This is called out explicitly per the task's "don't fabricate" instruction rather
than silently substituting.

## 8. Migration / LCM (separate API family — base path `interop/rest/v2`, NOT the Planning v3 API)

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| POST | `/interop/rest/v2/snapshots/export` | "LCM Export (v2)" — trigger a repeat export of a Migration artifact snapshot using previously configured export settings (payload: `SnapshotName`). Requires Service Administrator or the "Migrations - Administer" granular role. | destructive |
| POST | `/interop/rest/v2/snapshots/import` | "LCM Import (v2)" — import the contents of an application snapshot; optional `importUsers`, `userPassword`, `resetPassword` payload fields (importing users requires Identity Domain Administrator role). | destructive |
| GET | `/interop/rest/v2/migration/status` | "Get Migration Status (v2)" — retrieve migration (export/import) history: action type, duration, status (`Completed`/`Completed with warning`/`Failed`/`In Progress`), source/destination, per-artifact report with errors/warnings. | read |
| GET | `/interop/rest/v2/status/migration/{jobId}` | Poll status of an in-flight migration job by ID (confirmed as a "related endpoint" reference on the LCM Export page). | read |
| GET | `/interop/rest/v2/status/migration/{jobId}/{taskId}/details` | Get detailed task-level messages for a migration job (query params `limit`, `offset`, `msgtype`; confirmed as a related-endpoint reference on the LCM Export page). | read |
| GET | `/interop/rest/` | "Get REST API Versions for Migration" — list available Migration API versions with `lifecycle`/`latest` metadata. | read |

Additional Migration/LCM operations confirmed to exist (titles + page slugs only, from the crawled TOC at
`all_rest_apis_table.html`, not individually re-fetched for full method/path detail this session): Upload,
Download, List Files (v2/v3), Delete Files (v2/v3), Copy from/to Object Store (v1/v2/v3), Copy to/from SFTP,
Copy a File Between Instances (v1/v2), Clone an Environment, application-snapshot-specific
upload/download/copy/rename operations, and category/artifact-level operations (Export Categories Artifacts,
Get Categories, Get Snapshot Modification History, Import Snapshot Artifacts, List Artifacts in a
Category/Snapshot, List Import Options, Repeat Export Snapshot, Set Import Options) — all under `interop/rest/v2`
per the TOC's grouping and naming convention. A **first-generation, unversioned** variant (`lcm_import.html`,
`lcm_export.html`, `list_files.html`, `delete_files.html`) also still appears in the TOC under a "First
Generation REST APIs" heading — treat these as legacy/v1-equivalent and prefer the `_v2` pages for new
integration work.

Sources: [`lcm_export_v2.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/lcm_export_v2.html), [`lcm_import_v2.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/lcm_import_v2.html), [`migration_generate_status_report.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/migration_generate_status_report.html), [`get_rest_api_versions_for_lcm.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_rest_api_versions_for_lcm.html), and the TOC page [`all_rest_apis_table.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/all_rest_apis_table.html).

## 9. Access Permissions

No dedicated, general-purpose "read/assign security for an object (form, dimension, member)" REST resource
was found after targeted searching. What **is** confirmed is that ACL/security data moves through the generic
**Jobs** framework:

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/jobs` with `jobType: "IMPORT_SECURITY"` (also referenced in one fetched page as job type name `"Import Security"`) | Import ACL/security records (object name, user/group, access type, access mode) from a CSV file in the repository; `clearAll` flag to wipe existing permissions first. | destructive |
| POST | same job endpoint, `jobType: "EXPORT_SECURITY"` | Export ACL/security records to a CSV file. | read |
| POST | same job endpoint, `jobType: "IMPORT_CELL_LEVEL_SECURITY"` | Import cell-level security from a ZIP file. | destructive |
| POST | same job endpoint, `jobType: "EXPORT_CELL_LEVEL_SECURITY"` | Export cell-level security to a ZIP file. | read |

See section 10 (Not found in current docs) for the per-object, non-job-based permissions API that was searched
for and not located.

## 10. Substitution Variables

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| GET | `/HyperionPlanning/rest/{api_version}/applications/{application}/substitutionvariables` | Get all substitution variables defined for the application (across all plan types); each item carries `name`, `value`, `planType` (`ALL` or a specific plan type). | read |
| GET | `/HyperionPlanning/rest/{api_version}/applications/{application}/substitutionvariables/{name}` | Get a single substitution variable by name. **Live-confirmed quirk (2026-08-01):** returns `204 No Content` with an empty body for a real, existing variable name -- not an error, but not usable to retrieve the value either. Same request shape as the working list call, so this looks like a genuine Oracle limitation on this specific resource, not a client mistake. The wrapper returns `None` on a 204; prefer the list endpoint above and filter by name client-side. | read |
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/substitutionvariables` | Create or update substitution variables (upsert by name+scope); payload `{"items":[{"name","value","planType"}]}`. Returns HTTP 204 on success. | destructive |
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/substitutionvariables:delete` | Delete one or more substitution variables for the application (payload identifies items by name+planType). | destructive |

Additional plan-type-scoped and derived-variable read/delete operations are confirmed to **exist** via the
TOC (titles + slugs: `planning_get_subst_variables_defined_at_plan_type_level_5.html`,
`planning_get_derived_subst_variables_at_plan_type_level_6.html`,
`planning_get_derived_subst_variables_defined_at_plan_type_level_8.html`,
`planning_del_a_subst_variable_for_plantype.html`,
`planning_del_all_subst_variables_for_plantype.html`) but their exact path templates were not individually
re-fetched this session — treat as confirmed-to-exist, path-unconfirmed.

Sources: [`planning_get_all_subst_variables_for_app_1.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/planning_get_all_subst_variables_for_app_1.html), [`planning_get_a_subst_variable_for_app_2.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/planning_get_a_subst_variable_for_app_2.html), [`planning_create_or_replace_all_subst_variables_for_app_3.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/planning_create_or_replace_all_subst_variables_for_app_3.html), [`planning_del_all_subst_variables_for_app.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/planning_del_all_subst_variables_for_app.html).

## 11. Approvals (Planning Unit workflow)

Oracle documents this under "Planning Units," not the word "Approvals" — same feature (promote/reject/sign
off workflow).

**Request shape correction (2026-08-01):** the original Phase 0 research assumed a JSON POST body for all
three resources below (matching the task brief's general assumption). A live test against a real tenant
returned HTTP 415 "Unsupported Media Type" -- a bare framework-level (WebLogic/JAX-RS) rejection, no Oracle
application error payload -- for a JSON body on List All Planning Units. Re-fetching each resource's actual
documentation page confirmed **all three use `application/x-www-form-urlencoded`, not JSON**, and List All
Planning Units' `scenario`/`version` filter context is a `q` query parameter, not a body field at all. Fixed
in `endpoints/approvals.py`; the fix is live-confirmed for the two read operations, documentation-confirmed
(not live-tested, since it's destructive) for Change Planning Unit Status.

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/planningunits` | "List All Planning Units" — list planning units owned by the requesting user. **Live-confirmed (2026-08-01):** `scenario`/`version` go in a `q` query param as JSON (`{"scenario":...,"version":...}`), plus optional `offset`/`limit` query params; `filter` (optional, by e.g. `Status`/`SubStatus`) is an `application/x-www-form-urlencoded` body with repeated `filter=` fields, each shaped `{name:"Status",type:4,values:[2,5]}` (deliberately not valid JSON -- unquoted keys, matches Oracle's own example verbatim). | read |
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/planningunits/{puIdentifier}/availableactions` | "Get Available Planning Unit Actions" — list the next valid workflow actions (Promote, Sign Off, Reject, Delegate, Take Ownership, Originate, Freeze) for a planning unit owned by the caller. Optional `q={"options":0\|1}` query param (1=full approvals/default, 0=limited/mobile) and optional `application/x-www-form-urlencoded` `pmMembers=A,B,C` body. `puIdentifier` (e.g. `Forecast::"BU Version_1"`) must be URL-encoded in the path -- it can contain `:`, `"`, and spaces. | read |
| POST | `/HyperionPlanning/rest/{api_version}/applications/{application}/planningunits/{puhIdentifier}/actions` | "Change Planning Unit Status" — execute a workflow action via an `application/x-www-form-urlencoded` body: `actionId` (accepts either the string keyword or numeric code -- `PROMOTE`=6, `SIGN_OFF`=3, `APPROVE`=2, `DELEGATE`=7, `TAKE_OWNERSHIP`=8, `ORIGINATE`=9, `FREEZE`=10), optional `pmMembers`, optional `comments`. `puhIdentifier` must be URL-encoded in the path, same as above. | destructive |

Confirmed to exist but not re-fetched in full this session (titles/slugs from TOC): Get Planning Unit History
and Annotations (`get_planning_unit_history_and_annotations.html`), Get Planning Unit Promotional Path
(`get_planning_unit_promotional_path.html`), Get Planning Unit Owner Photo
(`get_a_planning_unit_owner_photo.html`), Get Filters with All Possible Values
(`get_filters_with_all_possible_values.html`).

Sources: [`list_all_planning_units.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/list_all_planning_units.html), [`get_available_planning_unit_actions.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/get_available_planning_unit_actions.html), [`change_planning_unit_status.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/change_planning_unit_status.html).

## 12. Smart Push / Data Management

No REST endpoint or Planning `jobType` literally named "Smart Push" was found — Smart Push is a Data
Management/Data Integration feature invoked either from the Planning UI's Job Console or, over REST, via the
generic Data Management job-submission endpoint below (confirmed to exist and cover Data Management job
execution broadly; the fetched pages for these two specific jobTypes did not themselves mention "Smart Push"
by name, so treat Smart Push coverage as **inferred, not textually confirmed**, pending a page specifically
about Smart Push execution).

| Method | Path Template | Purpose | Tag |
|---|---|---|---|
| POST | `/aif/rest/{api_version}/jobs` with `jobType: "pipeline"` | "Run a Pipeline" (Data Integration) — execute a Pipeline; payload `jobName` (Pipeline code), `variables` (e.g. `STARTPERIOD`, `ENDPERIOD`, `IMPORTMODE`, `EXPORTMODE`, `ATTACH_LOGS`, `SEND_MAIL`, `SEND_TO`). | destructive |
| POST | `/aif/rest/{api_version}/jobs` with `jobType: "DATARULE"` | "Run Data Rules in Data Management" — execute a data load rule; payload `jobName`, `startPeriod`, `endPeriod`, `importMode` (`APPEND`/`REPLACE`/`RECALCULATE`/`NONE`), `exportMode`, optional `fileName`. | destructive |
| POST | `/aif/rest/{api_version}/jobs` with `jobType: "BATCH"` (title/slug confirmed via TOC — `fdmee_run_batch.html`, "Running Batch Rules"; not independently re-fetched) | Execute a batch of Data Management load rules together. | destructive |
| GET | (job-status resource under `/aif/rest/{api_version}/...`; title confirmed via TOC as `fdmee_jobstatus_di.html` "Retrieve Job Status") | Poll Data Management job status. | read |

Sources: [`fdmee_run_pipeline.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/fdmee_run_pipeline.html), [`fdmee_run_data_rule.html`](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/prest/fdmee_run_data_rule.html).

## Not found in current docs

- **Dedicated per-object Access Permissions read/assign API** (i.e., something like
  `GET/PUT .../forms/{form}/accesspermissions` or `.../dimensions/{dim}/members/{member}/security`) — searched
  directly; only the job-based `IMPORT_SECURITY`/`EXPORT_SECURITY`/`IMPORT_CELL_LEVEL_SECURITY`/
  `EXPORT_CELL_LEVEL_SECURITY` job types (section 9) were confirmed. No non-job, synchronous CRUD endpoint for
  individual object ACLs was located in the crawled pages.
- **Task Lists (Planning UI feature — user-assigned workflow checklists inside a Planning application)** —
  searched directly. The only "task list"-shaped REST APIs found belong to a **different** Oracle EPM module,
  "Task Manager" (chapter intro at `task_manager_rest_apis_intro.html`, part of the FCCS/close-process family:
  deploy Task Manager templates, update task status for event monitoring, manage Oracle Integration Cloud
  connections). This is explicitly a distinct feature from Planning's in-app Task Lists, and no REST surface
  for Planning's own Task Lists (list/get/update status) was found.
- **Form definition (structure-only, no data) GET endpoint** — e.g. a `get_form.html`-style page describing a
  form's row/column/POV layout without pulling data. Only "Export Form Data" (which requires calling with
  `fields=gridInfo,pov` to approximate this) was found; no separate metadata-only resource was located.
- **Form-ID-scoped write/PATCH endpoint** (`PATCH .../forms/{form}/data`) — searched directly by several query
  variants; not found. Current documented write path is the plan-type-scoped Import Data Slice endpoint
  (section 5).
- **Literal `jobType` values `CLEAR_DATA` and `REFRESH_DATABASE`** as named in the task brief — not present in
  the fetched jobType enumeration; the current equivalents appear to be `CLEAR_CUBE` and `CUBE_REFRESH` (see
  section 7 note).
- **`compatibility_table_rest_apis.html`** — returned HTTP 404 at the two URL variants tried
  (`enterprise-performance-management-common/prest/` and `epm-cloud/prest/`); could not confirm its live
  current content this session even though it is referenced by Oracle's own search index and by the
  `all_rest_apis_table.html` navigation chain.

---

*Compiled from live fetches of `docs.oracle.com` on 2026-08-01. Do not treat any row above as stable across
Oracle releases without periodically re-verifying against the source pages, especially the Jobs — Typed table
(section 7), which Oracle revises most frequently.*
