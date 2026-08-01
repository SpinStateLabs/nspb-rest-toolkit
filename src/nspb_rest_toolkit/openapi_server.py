"""FastAPI OpenAPI tool server -- run with:

    python -m nspb_rest_toolkit.openapi_server

Exposes every operation in endpoints/ as a POST /tools/{operation} route
with a JSON body, so any OpenAPI-tool-calling client (Open WebUI's OpenAPI
tool server integration, or any other agent framework) can discover and
call them via /openapi.json. Mirrors mcp_server.py's tool set 1:1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .dashboard_api import router as dashboard_router
from .endpoints import applications as ep_applications
from .endpoints import approvals as ep_approvals
from .endpoints import data_management as ep_data_management
from .endpoints import dimensions as ep_dimensions
from .endpoints import forms as ep_forms
from .endpoints import jobs as ep_jobs
from .endpoints import migration as ep_migration
from .endpoints import security as ep_security
from .endpoints import substitution_variables as ep_subvars
from .exceptions import EPMToolkitError
from .runtime import connected_client, get_config

app = FastAPI(
    title="nspb-rest-toolkit",
    description=(
        "Direct REST toolkit for Oracle EPM Cloud Planning & Budgeting (NSPB). "
        "Reads are safe to call directly; destructive operations require "
        "confirm=true and must never be set true on the same turn as the "
        "user's first request -- see docs/SKILL.md."
    ),
    version="0.1.0",
)


app.include_router(dashboard_router)

_STATIC_DIR = Path(__file__).parent / "static"


@app.exception_handler(EPMToolkitError)
async def _epm_error_handler(request, exc: EPMToolkitError) -> JSONResponse:
    status_code = getattr(exc, "status_code", None) or 400
    return JSONResponse(status_code=status_code, content={"error": type(exc).__name__, "detail": str(exc)})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the connections-management dashboard -- see dashboard_api.py for its API."""
    return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/connections")
async def list_connections() -> list[dict[str, str]]:
    """List configured customer connections (slug + display name only -- no credentials)."""
    cfg = get_config()
    return [{"slug": slug, "display_name": conn.display_name} for slug, conn in cfg.connections.items()]


# ---- Applications -----------------------------------------------------------


class ApplicationRequest(BaseModel):
    connection: str


@app.post("/tools/list_applications", summary="List Planning applications", tags=["applications"])
async def list_applications(body: ApplicationRequest) -> list[dict[str, Any]]:
    """List the Planning applications the connection's credentials are assigned to. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_applications.list_applications(client)


class ApplicationSummaryRequest(BaseModel):
    connection: str
    application: str


@app.post("/tools/get_application_summary", summary="Get application summary", tags=["applications"])
async def get_application_summary(body: ApplicationSummaryRequest) -> dict[str, Any]:
    """Get an automation-oriented summary of an application's structure. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_applications.get_application_summary(client, body.application)


# ---- Dimensions / Members -----------------------------------------------------


class PlanTypesRequest(BaseModel):
    connection: str
    application: str


@app.post("/tools/list_plan_types", summary="List plan types", tags=["dimensions"])
async def list_plan_types(body: PlanTypesRequest) -> list[dict[str, Any]]:
    """List plan types (cubes) for an application. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_dimensions.list_plan_types(client, body.application)


class DimensionsRequest(BaseModel):
    connection: str
    application: str
    plantype: str


@app.post("/tools/list_dimensions", summary="List dimensions", tags=["dimensions"])
async def list_dimensions(body: DimensionsRequest) -> list[dict[str, Any]]:
    """List dimensions associated with a plan type. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_dimensions.list_dimensions(client, body.application, body.plantype)


class DimensionRequest(BaseModel):
    connection: str
    application: str
    plantype: str
    dimension: str


@app.post("/tools/get_dimension", summary="Get dimension details", tags=["dimensions"])
async def get_dimension(body: DimensionRequest) -> dict[str, Any]:
    """Get a dimension's hierarchy/details. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_dimensions.get_dimension(client, body.application, body.plantype, body.dimension)


class MemberRequest(BaseModel):
    connection: str
    application: str
    dimension: str
    member: str


@app.post("/tools/get_member", summary="Get member properties", tags=["dimensions"])
async def get_member(body: MemberRequest) -> dict[str, Any]:
    """Get a single member's properties. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_dimensions.get_member(client, body.application, body.dimension, body.member)


class AddMemberRequest(BaseModel):
    connection: str
    application: str
    dimension: str
    member_name: str
    parent_name: str
    confirm: bool = False


@app.post("/tools/add_member", summary="Add a dimension member (DESTRUCTIVE)", tags=["dimensions"])
async def add_member(body: AddMemberRequest) -> dict[str, Any]:
    """Add a new member under a parent in a dimension outline. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request -- describe the change and wait for explicit confirmation.
    """
    async with connected_client(body.connection) as client:
        return await ep_dimensions.add_member(
            client, body.application, body.dimension, body.member_name, body.parent_name, confirm=body.confirm
        )


# ---- Forms --------------------------------------------------------------------


class FormShapeRequest(BaseModel):
    connection: str
    application: str
    form: str


@app.post("/tools/read_form_grid_shape", summary="Discover a form's grid shape", tags=["forms"])
async def read_form_grid_shape(body: FormShapeRequest) -> dict[str, Any]:
    """Discover a form's POV/grid shape without pulling full data. Read-only.

    ALWAYS call this before write_form_data for any form not already
    inspected in this conversation -- never guess a grid shape.
    """
    async with connected_client(body.connection) as client:
        return await ep_forms.read_form_grid_shape(client, body.application, body.form)


class FormDataRequest(BaseModel):
    connection: str
    application: str
    form: str
    page_member_list: str | None = None
    display_member_as: str | None = None
    force_start_expanded: bool | None = None
    filter_members: str | None = None
    fields: str | None = None


@app.post("/tools/read_form_data", summary="Read form data grid", tags=["forms"])
async def read_form_data(body: FormDataRequest) -> dict[str, Any]:
    """Read the full data grid for a Planning form. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_forms.read_form_data(
            client,
            body.application,
            body.form,
            page_member_list=body.page_member_list,
            display_member_as=body.display_member_as,
            force_start_expanded=body.force_start_expanded,
            filter_members=body.filter_members,
            fields=body.fields,
        )


class ExportDataSliceRequest(BaseModel):
    connection: str
    application: str
    plantype: str
    grid_definition: dict[str, Any]


@app.post("/tools/export_data_slice", summary="Export an arbitrary data slice", tags=["forms"])
async def export_data_slice(body: ExportDataSliceRequest) -> dict[str, Any]:
    """Export a JSON data grid for an arbitrary region. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_forms.export_data_slice(client, body.application, body.plantype, body.grid_definition)


class ExportDataRequest(BaseModel):
    connection: str
    application: str
    plantype: str
    query_definition: dict[str, Any]


@app.post("/tools/export_data", summary="Export data via axis query", tags=["forms"])
async def export_data(body: ExportDataRequest) -> dict[str, Any]:
    """Export data via an axis-based query definition. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_forms.export_data(client, body.application, body.plantype, body.query_definition)


class WriteFormDataRequest(BaseModel):
    connection: str
    application: str
    plantype: str
    grid: dict[str, Any]
    aggregate_essbase_data: bool | None = None
    cell_notes_option: str | None = None
    date_format: str | None = None
    confirm: bool = False


@app.post("/tools/write_form_data", summary="Write a data grid (DESTRUCTIVE)", tags=["forms"])
async def write_form_data(body: WriteFormDataRequest) -> dict[str, Any]:
    """Write a data grid into a plan type (form-data write). DESTRUCTIVE.

    `grid` MUST come from a read_form_grid_shape/read_form_data call made
    earlier in THIS conversation -- never guess the shape. Never call with
    confirm=true on the same turn as the user's first request to write
    data -- describe exactly what will change and wait for explicit
    confirmation, then call again with confirm=true.
    """
    async with connected_client(body.connection) as client:
        return await ep_forms.write_form_data(
            client,
            body.application,
            body.plantype,
            body.grid,
            aggregate_essbase_data=body.aggregate_essbase_data,
            cell_notes_option=body.cell_notes_option,
            date_format=body.date_format,
            confirm=body.confirm,
        )


class ClearDataSliceRequest(BaseModel):
    connection: str
    application: str
    plantype: str
    grid_definition: dict[str, Any]
    clear_essbase_data: bool | None = None
    clear_planning_data: bool | None = None
    confirm: bool = False


@app.post("/tools/clear_data_slice", summary="Clear a data slice (DESTRUCTIVE)", tags=["forms"])
async def clear_data_slice(body: ClearDataSliceRequest) -> dict[str, Any]:
    """Clear Planning/Essbase data for a region. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request.
    """
    async with connected_client(body.connection) as client:
        return await ep_forms.clear_data_slice(
            client,
            body.application,
            body.plantype,
            body.grid_definition,
            clear_essbase_data=body.clear_essbase_data,
            clear_planning_data=body.clear_planning_data,
            confirm=body.confirm,
        )


# ---- Jobs -----------------------------------------------------------------------


class SubmitJobRequest(BaseModel):
    connection: str
    application: str
    job_type: str
    job_name: str
    parameters: dict[str, Any] | None = None
    confirm: bool = False


@app.post("/tools/submit_job", summary="Submit a Planning job (mostly DESTRUCTIVE)", tags=["jobs"])
async def submit_job(body: SubmitJobRequest) -> dict[str, Any]:
    """Submit a Planning job by jobType. Most job types are DESTRUCTIVE (see jobs.JOB_TYPE_TAGS).

    Never call with confirm=true on the same turn as the user's first
    request -- describe what the job will do and wait for explicit
    confirmation.
    """
    async with connected_client(body.connection) as client:
        return await ep_jobs.submit_job(
            client, body.application, body.job_type, body.job_name, parameters=body.parameters, confirm=body.confirm
        )


class JobStatusRequest(BaseModel):
    connection: str
    application: str
    job_id: str


@app.post("/tools/get_job_status", summary="Get job status", tags=["jobs"])
async def get_job_status(body: JobStatusRequest) -> dict[str, Any]:
    """Retrieve the current status of a submitted job. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_jobs.get_job_status(client, body.application, body.job_id)


@app.post("/tools/poll_job_status", summary="Poll job to a terminal state", tags=["jobs"])
async def poll_job_status(body: JobStatusRequest) -> dict[str, Any]:
    """Poll a submitted job to a terminal state (Completed/Error/Invalid). Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_jobs.poll_job_status(client, body.application, body.job_id)


class RunBusinessRuleRequest(BaseModel):
    connection: str
    application: str
    rule_name: str
    runtime_prompts: dict[str, Any] | None = None
    confirm: bool = False


@app.post("/tools/run_business_rule", summary="Run a business rule (DESTRUCTIVE)", tags=["jobs"])
async def run_business_rule(body: RunBusinessRuleRequest) -> dict[str, Any]:
    """Launch a Planning business rule by exact name. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request -- describe which rule and what it does, wait for explicit
    confirmation, then call again with confirm=true.
    """
    async with connected_client(body.connection) as client:
        return await ep_jobs.run_business_rule(
            client, body.application, body.rule_name, runtime_prompts=body.runtime_prompts, confirm=body.confirm
        )


# ---- Migration / LCM -------------------------------------------------------------


class ExportSnapshotRequest(BaseModel):
    connection: str
    snapshot_name: str
    confirm: bool = False


@app.post("/tools/export_snapshot", summary="Export an LCM snapshot (DESTRUCTIVE)", tags=["migration"])
async def export_snapshot(body: ExportSnapshotRequest) -> dict[str, Any]:
    """Trigger a repeat export of a Migration artifact snapshot. DESTRUCTIVE."""
    async with connected_client(body.connection) as client:
        return await ep_migration.export_snapshot(client, body.snapshot_name, confirm=body.confirm)


class ImportSnapshotRequest(BaseModel):
    connection: str
    snapshot_name: str
    import_users: bool | None = None
    user_password: str | None = None
    reset_password: bool | None = None
    confirm: bool = False


@app.post("/tools/import_snapshot", summary="Import an LCM snapshot (DESTRUCTIVE)", tags=["migration"])
async def import_snapshot(body: ImportSnapshotRequest) -> dict[str, Any]:
    """Import the contents of an application snapshot -- overwrites application content. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request -- describe exactly what will be overwritten and wait for
    explicit confirmation.
    """
    async with connected_client(body.connection) as client:
        return await ep_migration.import_snapshot(
            client,
            body.snapshot_name,
            import_users=body.import_users,
            user_password=body.user_password,
            reset_password=body.reset_password,
            confirm=body.confirm,
        )


class ConnectionOnlyRequest(BaseModel):
    connection: str


@app.post("/tools/get_migration_status", summary="Get migration history", tags=["migration"])
async def get_migration_status(body: ConnectionOnlyRequest) -> dict[str, Any]:
    """Get migration (export/import) history. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_migration.get_migration_status(client)


class MigrationJobRequest(BaseModel):
    connection: str
    job_id: str


@app.post("/tools/get_migration_job_status", summary="Get migration job status", tags=["migration"])
async def get_migration_job_status(body: MigrationJobRequest) -> dict[str, Any]:
    """Poll the status of an in-flight migration job by ID. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_migration.get_migration_job_status(client, body.job_id)


@app.post("/tools/poll_migration_job", summary="Poll migration job to terminal state", tags=["migration"])
async def poll_migration_job(body: MigrationJobRequest) -> dict[str, Any]:
    """Poll a migration job to a terminal state. Read-only.

    A returned status of 1 ("completed with issues") is a valid terminal
    state, not an error -- call get_migration_job_task_details next to see
    what happened.
    """
    async with connected_client(body.connection) as client:
        return await ep_migration.poll_migration_job(client, body.job_id)


class MigrationJobTaskDetailsRequest(BaseModel):
    connection: str
    job_id: str
    task_id: str
    limit: int | None = None
    offset: int | None = None
    msgtype: str | None = None


@app.post("/tools/get_migration_job_task_details", summary="Get migration task details", tags=["migration"])
async def get_migration_job_task_details(body: MigrationJobTaskDetailsRequest) -> dict[str, Any]:
    """Get detailed task-level messages for a migration job. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_migration.get_migration_job_task_details(
            client, body.job_id, body.task_id, limit=body.limit, offset=body.offset, msgtype=body.msgtype
        )


@app.post("/tools/get_migration_api_versions", summary="List Migration API versions", tags=["migration"])
async def get_migration_api_versions(body: ConnectionOnlyRequest) -> dict[str, Any]:
    """List available Migration API versions. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_migration.get_migration_api_versions(client)


# ---- Access Permissions (security, job-based) -------------------------------------


class ImportSecurityRequest(BaseModel):
    connection: str
    application: str
    file_name: str
    clear_all: bool | None = None
    error_file: str | None = None
    confirm: bool = False


@app.post("/tools/import_security", summary="Import ACL/security records (DESTRUCTIVE)", tags=["security"])
async def import_security(body: ImportSecurityRequest) -> dict[str, Any]:
    """Import ACL/security records from a CSV file in the repository. DESTRUCTIVE.

    clear_all=true wipes existing permissions first -- call that out
    explicitly when describing this action. Never call with confirm=true on
    the same turn as the user's first request.
    """
    async with connected_client(body.connection) as client:
        return await ep_security.import_security(
            client, body.application, body.file_name, clear_all=body.clear_all, error_file=body.error_file,
            confirm=body.confirm,
        )


class SecurityFileRequest(BaseModel):
    connection: str
    application: str
    file_name: str


@app.post("/tools/export_security", summary="Export ACL/security records", tags=["security"])
async def export_security(body: SecurityFileRequest) -> dict[str, Any]:
    """Export ACL/security records to a CSV file. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_security.export_security(client, body.application, body.file_name)


class ImportCellSecurityRequest(BaseModel):
    connection: str
    application: str
    file_name: str
    confirm: bool = False


@app.post(
    "/tools/import_cell_level_security", summary="Import cell-level security (DESTRUCTIVE)", tags=["security"]
)
async def import_cell_level_security(body: ImportCellSecurityRequest) -> dict[str, Any]:
    """Import cell-level security from a ZIP file. DESTRUCTIVE."""
    async with connected_client(body.connection) as client:
        return await ep_security.import_cell_level_security(
            client, body.application, body.file_name, confirm=body.confirm
        )


@app.post("/tools/export_cell_level_security", summary="Export cell-level security", tags=["security"])
async def export_cell_level_security(body: SecurityFileRequest) -> dict[str, Any]:
    """Export cell-level security to a ZIP file. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_security.export_cell_level_security(client, body.application, body.file_name)


# ---- Substitution Variables ---------------------------------------------------------


@app.post("/tools/list_substitution_variables", summary="List substitution variables", tags=["substitution_variables"])
async def list_substitution_variables(body: PlanTypesRequest) -> list[dict[str, Any]]:
    """Get all substitution variables for an application. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_subvars.list_substitution_variables(client, body.application)


class SubstitutionVariableRequest(BaseModel):
    connection: str
    application: str
    name: str


@app.post("/tools/get_substitution_variable", summary="Get a substitution variable", tags=["substitution_variables"])
async def get_substitution_variable(body: SubstitutionVariableRequest) -> dict[str, Any]:
    """Get a single substitution variable by name. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_subvars.get_substitution_variable(client, body.application, body.name)


class SubstitutionVariablesWriteRequest(BaseModel):
    connection: str
    application: str
    variables: list[dict[str, Any]]
    confirm: bool = False


@app.post(
    "/tools/set_substitution_variables", summary="Create/update substitution variables (DESTRUCTIVE)",
    tags=["substitution_variables"],
)
async def set_substitution_variables(body: SubstitutionVariablesWriteRequest) -> dict[str, str]:
    """Create or update substitution variables. DESTRUCTIVE.

    `variables` is a list of {"name", "value", "planType"}. Never call with
    confirm=true on the same turn as the user's first request -- list the
    names/values that will change and wait for explicit confirmation.
    """
    async with connected_client(body.connection) as client:
        await ep_subvars.set_substitution_variables(client, body.application, body.variables, confirm=body.confirm)
    return {"status": "ok"}


@app.post(
    "/tools/delete_substitution_variables", summary="Delete substitution variables (DESTRUCTIVE)",
    tags=["substitution_variables"],
)
async def delete_substitution_variables(body: SubstitutionVariablesWriteRequest) -> dict[str, str]:
    """Delete substitution variables. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request.
    """
    async with connected_client(body.connection) as client:
        await ep_subvars.delete_substitution_variables(
            client, body.application, body.variables, confirm=body.confirm
        )
    return {"status": "ok"}


# ---- Approvals (Planning Units) ----------------------------------------------------


class ListPlanningUnitsRequest(BaseModel):
    connection: str
    application: str
    filter: dict[str, Any] | None = None
    offset: int | None = None
    limit: int | None = None


@app.post("/tools/list_planning_units", summary="List planning units", tags=["approvals"])
async def list_planning_units(body: ListPlanningUnitsRequest) -> dict[str, Any]:
    """List planning units owned by the caller. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_approvals.list_planning_units(
            client, body.application, filter=body.filter, offset=body.offset, limit=body.limit
        )


class AvailableActionsRequest(BaseModel):
    connection: str
    application: str
    pu_identifier: str


@app.post("/tools/get_available_actions", summary="Get available planning unit actions", tags=["approvals"])
async def get_available_actions(body: AvailableActionsRequest) -> dict[str, Any]:
    """List valid next workflow actions for a planning unit. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_approvals.get_available_actions(client, body.application, body.pu_identifier)


class ChangePlanningUnitStatusRequest(BaseModel):
    connection: str
    application: str
    puh_identifier: str
    action: str
    pm_members: list[str] | None = None
    comments: str | None = None
    confirm: bool = False


@app.post(
    "/tools/change_planning_unit_status", summary="Change planning unit status (DESTRUCTIVE)", tags=["approvals"]
)
async def change_planning_unit_status(body: ChangePlanningUnitStatusRequest) -> dict[str, Any]:
    """Execute a Planning Unit workflow action (promote/sign off/reject/etc.). DESTRUCTIVE.

    Call get_available_actions first to confirm the action is valid for the
    unit's current status. Never call with confirm=true on the same turn as
    the user's first request.
    """
    async with connected_client(body.connection) as client:
        return await ep_approvals.change_planning_unit_status(
            client,
            body.application,
            body.puh_identifier,
            body.action,
            pm_members=body.pm_members,
            comments=body.comments,
            confirm=body.confirm,
        )


# ---- Smart Push / Data Management --------------------------------------------------


class RunPipelineRequest(BaseModel):
    connection: str
    pipeline_code: str
    start_period: str | None = None
    end_period: str | None = None
    import_mode: str | None = None
    export_mode: str | None = None
    confirm: bool = False


@app.post("/tools/run_pipeline", summary="Run a Data Integration pipeline (DESTRUCTIVE)", tags=["data_management"])
async def run_pipeline(body: RunPipelineRequest) -> dict[str, Any]:
    """Execute a Data Integration Pipeline by code. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request.
    """
    async with connected_client(body.connection) as client:
        return await ep_data_management.run_pipeline(
            client,
            body.pipeline_code,
            start_period=body.start_period,
            end_period=body.end_period,
            import_mode=body.import_mode,
            export_mode=body.export_mode,
            confirm=body.confirm,
        )


class RunDataRuleRequest(BaseModel):
    connection: str
    rule_name: str
    start_period: str | None = None
    end_period: str | None = None
    import_mode: str | None = None
    export_mode: str | None = None
    confirm: bool = False


@app.post("/tools/run_data_rule", summary="Run a Data Management data rule (DESTRUCTIVE)", tags=["data_management"])
async def run_data_rule(body: RunDataRuleRequest) -> dict[str, Any]:
    """Execute a Data Management data load rule. DESTRUCTIVE.

    Never call with confirm=true on the same turn as the user's first
    request.
    """
    async with connected_client(body.connection) as client:
        return await ep_data_management.run_data_rule(
            client,
            body.rule_name,
            start_period=body.start_period,
            end_period=body.end_period,
            import_mode=body.import_mode,
            export_mode=body.export_mode,
            confirm=body.confirm,
        )


class RunBatchRequest(BaseModel):
    connection: str
    batch_name: str
    confirm: bool = False


@app.post("/tools/run_batch", summary="Run a Data Management batch (DESTRUCTIVE)", tags=["data_management"])
async def run_batch(body: RunBatchRequest) -> dict[str, Any]:
    """Execute a batch of Data Management load rules together. DESTRUCTIVE."""
    async with connected_client(body.connection) as client:
        return await ep_data_management.run_batch(client, body.batch_name, confirm=body.confirm)


class DataManagementJobRequest(BaseModel):
    connection: str
    job_id: str


@app.post("/tools/get_data_management_job_status", summary="Get Data Management job status", tags=["data_management"])
async def get_data_management_job_status(body: DataManagementJobRequest) -> dict[str, Any]:
    """Poll a Data Management job's status. Read-only."""
    async with connected_client(body.connection) as client:
        return await ep_data_management.get_data_management_job_status(client, body.job_id)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
