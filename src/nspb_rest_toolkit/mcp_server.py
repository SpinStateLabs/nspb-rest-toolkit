"""MCP stdio server for Claude Desktop/Code.

Install with:
    claude mcp add nspb-rest -- python -m nspb_rest_toolkit.mcp_server

Every tool takes `connection` as its first argument -- the slug of a
customer connection defined in connections.yaml (see config.py / README).
Destructive tools take `confirm: bool = False` as their last argument and
raise if called with confirm=True on the same turn the user first asked for
the action -- see docs/SKILL.md, which this server also exposes as an MCP
resource so a calling model can read it directly.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .endpoints import (
    applications as ep_applications,
)
from .endpoints import (
    approvals as ep_approvals,
)
from .endpoints import (
    data_management as ep_data_management,
)
from .endpoints import (
    dimensions as ep_dimensions,
)
from .endpoints import (
    forms as ep_forms,
)
from .endpoints import (
    jobs as ep_jobs,
)
from .endpoints import (
    migration as ep_migration,
)
from .endpoints import (
    security as ep_security,
)
from .endpoints import (
    substitution_variables as ep_subvars,
)
from .runtime import connected_client, get_config

mcp = MCPServer("nspb-rest-toolkit")


_SKILL_SUMMARY = """\
# nspb-rest-toolkit safety guidance (summary -- full text in docs/SKILL.md)

1. Reads (list/get/export) are safe to call with no gating.
2. Destructive operations (writes, business rules, jobs, snapshot import,
   security import, substitution-variable writes, planning-unit actions,
   pipeline/data-rule runs) require confirm=True.
3. NEVER call a destructive tool with confirm=True on the same turn as the
   user's first request, regardless of phrasing ("run the X rule" is not
   itself confirmation). Describe what will change, wait for the user's
   explicit confirmation, THEN call again with confirm=True.
4. For form-data writes specifically: ALWAYS call read_form_grid_shape (or
   read_form_data) for the target form/plantype first, in this same
   conversation, before building a write_form_data grid body. Never guess a
   grid shape from a prior session or training data -- forms change.
5. auth_method (basic / oauth2 / bearer_token) only changes how the
   toolkit authenticates to Oracle -- it does not change any of the above.
   An auth failure on an oauth2 or bearer_token connection needs a human
   out-of-band fix (re-run `python -m nspb_rest_toolkit.oauth2_bootstrap`,
   or regenerate the static token) -- report the error, don't retry it or
   ask the user for a raw token/password. See docs/SKILL.md section 6.
"""


@mcp.resource("nspb://skill")
def skill_guidance() -> str:
    """Safety and usage guidance for calling this server's tools (reads vs. destructive, form-write sequencing)."""
    return _SKILL_SUMMARY


@mcp.tool()
def list_connections() -> list[dict[str, str]]:
    """List configured customer connections (slug + display name only -- no credentials)."""
    cfg = get_config()
    return [{"slug": slug, "display_name": conn.display_name} for slug, conn in cfg.connections.items()]


# ---- Applications -----------------------------------------------------------


@mcp.tool()
async def list_applications(connection: str) -> list[dict[str, Any]]:
    """List the Planning applications the connection's credentials are assigned to. Read-only."""
    async with connected_client(connection) as client:
        return await ep_applications.list_applications(client)


@mcp.tool()
async def get_application_summary(connection: str, application: str) -> dict[str, Any]:
    """Get an automation-oriented summary of an application's structure. Read-only."""
    async with connected_client(connection) as client:
        return await ep_applications.get_application_summary(client, application)


# ---- Dimensions / Members ---------------------------------------------------


@mcp.tool()
async def list_plan_types(connection: str, application: str) -> list[dict[str, Any]]:
    """List plan types (cubes) for an application. Read-only."""
    async with connected_client(connection) as client:
        return await ep_dimensions.list_plan_types(client, application)


@mcp.tool()
async def list_dimensions(connection: str, application: str, plantype: str) -> list[dict[str, Any]]:
    """List dimensions associated with a plan type. Read-only."""
    async with connected_client(connection) as client:
        return await ep_dimensions.list_dimensions(client, application, plantype)


@mcp.tool()
async def get_dimension(connection: str, application: str, plantype: str, dimension: str) -> dict[str, Any]:
    """Get a dimension's hierarchy/details. Read-only."""
    async with connected_client(connection) as client:
        return await ep_dimensions.get_dimension(client, application, plantype, dimension)


@mcp.tool()
async def get_member(connection: str, application: str, dimension: str, member: str) -> dict[str, Any]:
    """Get a single member's properties. Read-only."""
    async with connected_client(connection) as client:
        return await ep_dimensions.get_member(client, application, dimension, member)


@mcp.tool()
async def add_member(
    connection: str,
    application: str,
    dimension: str,
    member_name: str,
    parent_name: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Add a new member under a parent in a dimension outline. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request -- describe the change and wait for explicit confirmation.
    """
    async with connected_client(connection) as client:
        return await ep_dimensions.add_member(
            client, application, dimension, member_name, parent_name, confirm=confirm
        )


# ---- Forms -------------------------------------------------------------------


@mcp.tool()
async def read_form_grid_shape(connection: str, application: str, form: str) -> dict[str, Any]:
    """Discover a form's POV/grid shape without pulling full data. Read-only.

    ALWAYS call this before write_form_data for any form not already
    inspected in this conversation -- never guess a grid shape.
    """
    async with connected_client(connection) as client:
        return await ep_forms.read_form_grid_shape(client, application, form)


@mcp.tool()
async def read_form_data(
    connection: str,
    application: str,
    form: str,
    page_member_list: str | None = None,
    display_member_as: str | None = None,
    force_start_expanded: bool | None = None,
    filter_members: str | None = None,
    fields: str | None = None,
) -> dict[str, Any]:
    """Read the full data grid for a Planning form. Read-only."""
    async with connected_client(connection) as client:
        return await ep_forms.read_form_data(
            client,
            application,
            form,
            page_member_list=page_member_list,
            display_member_as=display_member_as,
            force_start_expanded=force_start_expanded,
            filter_members=filter_members,
            fields=fields,
        )


@mcp.tool()
async def export_data_slice(
    connection: str, application: str, plantype: str, grid_definition: dict[str, Any]
) -> dict[str, Any]:
    """Export a JSON data grid for an arbitrary region. Read-only."""
    async with connected_client(connection) as client:
        return await ep_forms.export_data_slice(client, application, plantype, grid_definition)


@mcp.tool()
async def export_data(
    connection: str, application: str, plantype: str, query_definition: dict[str, Any]
) -> dict[str, Any]:
    """Export data via an axis-based query definition. Read-only."""
    async with connected_client(connection) as client:
        return await ep_forms.export_data(client, application, plantype, query_definition)


@mcp.tool()
async def write_form_data(
    connection: str,
    application: str,
    plantype: str,
    grid: dict[str, Any],
    aggregate_essbase_data: bool | None = None,
    cell_notes_option: str | None = None,
    date_format: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Write a data grid into a plan type (form-data write). DESTRUCTIVE.

    `grid` MUST come from a read_form_grid_shape/read_form_data call made
    earlier in THIS conversation -- never guess the shape. Never call with
    confirm=True on the same turn as the user's first request to write
    data -- describe exactly what will change and wait for explicit
    confirmation, then call again with confirm=True.
    """
    async with connected_client(connection) as client:
        return await ep_forms.write_form_data(
            client,
            application,
            plantype,
            grid,
            aggregate_essbase_data=aggregate_essbase_data,
            cell_notes_option=cell_notes_option,
            date_format=date_format,
            confirm=confirm,
        )


@mcp.tool()
async def clear_data_slice(
    connection: str,
    application: str,
    plantype: str,
    grid_definition: dict[str, Any],
    clear_essbase_data: bool | None = None,
    clear_planning_data: bool | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Clear Planning/Essbase data for a region. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request.
    """
    async with connected_client(connection) as client:
        return await ep_forms.clear_data_slice(
            client,
            application,
            plantype,
            grid_definition,
            clear_essbase_data=clear_essbase_data,
            clear_planning_data=clear_planning_data,
            confirm=confirm,
        )


# ---- Jobs ----------------------------------------------------------------------


@mcp.tool()
async def submit_job(
    connection: str,
    application: str,
    job_type: str,
    job_name: str,
    parameters: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Submit a Planning job by jobType. Most job types are DESTRUCTIVE (see jobs.JOB_TYPE_TAGS).

    Never call with confirm=True on the same turn as the user's first
    request -- describe what the job will do and wait for explicit
    confirmation.
    """
    async with connected_client(connection) as client:
        return await ep_jobs.submit_job(
            client, application, job_type, job_name, parameters=parameters, confirm=confirm
        )


@mcp.tool()
async def get_job_status(connection: str, application: str, job_id: str) -> dict[str, Any]:
    """Retrieve the current status of a submitted job. Read-only."""
    async with connected_client(connection) as client:
        return await ep_jobs.get_job_status(client, application, job_id)


@mcp.tool()
async def poll_job_status(connection: str, application: str, job_id: str) -> dict[str, Any]:
    """Poll a submitted job to a terminal state (Completed/Error/Invalid). Read-only."""
    async with connected_client(connection) as client:
        return await ep_jobs.poll_job_status(client, application, job_id)


@mcp.tool()
async def run_business_rule(
    connection: str,
    application: str,
    rule_name: str,
    runtime_prompts: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Launch a Planning business rule by exact name. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request -- describe which rule and what it does, wait for explicit
    confirmation, then call again with confirm=True.
    """
    async with connected_client(connection) as client:
        return await ep_jobs.run_business_rule(
            client, application, rule_name, runtime_prompts=runtime_prompts, confirm=confirm
        )


# ---- Migration / LCM -----------------------------------------------------------


@mcp.tool()
async def export_snapshot(connection: str, snapshot_name: str, confirm: bool = False) -> dict[str, Any]:
    """Trigger a repeat export of a Migration artifact snapshot. DESTRUCTIVE."""
    async with connected_client(connection) as client:
        return await ep_migration.export_snapshot(client, snapshot_name, confirm=confirm)


@mcp.tool()
async def import_snapshot(
    connection: str,
    snapshot_name: str,
    import_users: bool | None = None,
    user_password: str | None = None,
    reset_password: bool | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import the contents of an application snapshot -- overwrites application content. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request -- describe exactly what will be overwritten and wait for
    explicit confirmation.
    """
    async with connected_client(connection) as client:
        return await ep_migration.import_snapshot(
            client,
            snapshot_name,
            import_users=import_users,
            user_password=user_password,
            reset_password=reset_password,
            confirm=confirm,
        )


@mcp.tool()
async def get_migration_status(connection: str) -> dict[str, Any]:
    """Get migration (export/import) history. Read-only."""
    async with connected_client(connection) as client:
        return await ep_migration.get_migration_status(client)


@mcp.tool()
async def get_migration_job_status(connection: str, job_id: str) -> dict[str, Any]:
    """Poll the status of an in-flight migration job by ID. Read-only."""
    async with connected_client(connection) as client:
        return await ep_migration.get_migration_job_status(client, job_id)


@mcp.tool()
async def poll_migration_job(connection: str, job_id: str) -> dict[str, Any]:
    """Poll a migration job to a terminal state. Read-only.

    A returned status of 1 ("completed with issues") is a valid terminal
    state, not an error -- call get_migration_job_task_details next to see
    what happened.
    """
    async with connected_client(connection) as client:
        return await ep_migration.poll_migration_job(client, job_id)


@mcp.tool()
async def get_migration_job_task_details(
    connection: str,
    job_id: str,
    task_id: str,
    limit: int | None = None,
    offset: int | None = None,
    msgtype: str | None = None,
) -> dict[str, Any]:
    """Get detailed task-level messages for a migration job. Read-only."""
    async with connected_client(connection) as client:
        return await ep_migration.get_migration_job_task_details(
            client, job_id, task_id, limit=limit, offset=offset, msgtype=msgtype
        )


@mcp.tool()
async def get_migration_api_versions(connection: str) -> dict[str, Any]:
    """List available Migration API versions. Read-only."""
    async with connected_client(connection) as client:
        return await ep_migration.get_migration_api_versions(client)


# ---- Access Permissions (security, job-based) -----------------------------------


@mcp.tool()
async def import_security(
    connection: str,
    application: str,
    file_name: str,
    clear_all: bool | None = None,
    error_file: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Import ACL/security records from a CSV file in the repository. DESTRUCTIVE.

    clear_all=True wipes existing permissions first -- call that out
    explicitly when describing this action. Never call with confirm=True
    on the same turn as the user's first request.
    """
    async with connected_client(connection) as client:
        return await ep_security.import_security(
            client, application, file_name, clear_all=clear_all, error_file=error_file, confirm=confirm
        )


@mcp.tool()
async def export_security(connection: str, application: str, file_name: str) -> dict[str, Any]:
    """Export ACL/security records to a CSV file. Read-only."""
    async with connected_client(connection) as client:
        return await ep_security.export_security(client, application, file_name)


@mcp.tool()
async def import_cell_level_security(
    connection: str, application: str, file_name: str, confirm: bool = False
) -> dict[str, Any]:
    """Import cell-level security from a ZIP file. DESTRUCTIVE."""
    async with connected_client(connection) as client:
        return await ep_security.import_cell_level_security(client, application, file_name, confirm=confirm)


@mcp.tool()
async def export_cell_level_security(connection: str, application: str, file_name: str) -> dict[str, Any]:
    """Export cell-level security to a ZIP file. Read-only."""
    async with connected_client(connection) as client:
        return await ep_security.export_cell_level_security(client, application, file_name)


# ---- Substitution Variables -----------------------------------------------------


@mcp.tool()
async def list_substitution_variables(connection: str, application: str) -> list[dict[str, Any]]:
    """Get all substitution variables for an application. Read-only."""
    async with connected_client(connection) as client:
        return await ep_subvars.list_substitution_variables(client, application)


@mcp.tool()
async def get_substitution_variable(connection: str, application: str, name: str) -> dict[str, Any]:
    """Get a single substitution variable by name. Read-only."""
    async with connected_client(connection) as client:
        return await ep_subvars.get_substitution_variable(client, application, name)


@mcp.tool()
async def set_substitution_variables(
    connection: str, application: str, variables: list[dict[str, Any]], confirm: bool = False
) -> str:
    """Create or update substitution variables. DESTRUCTIVE.

    `variables` is a list of {"name", "value", "planType"}. Never call with
    confirm=True on the same turn as the user's first request -- list the
    names/values that will change and wait for explicit confirmation.
    """
    async with connected_client(connection) as client:
        await ep_subvars.set_substitution_variables(client, application, variables, confirm=confirm)
    return "ok"


@mcp.tool()
async def delete_substitution_variables(
    connection: str, application: str, variables: list[dict[str, Any]], confirm: bool = False
) -> str:
    """Delete substitution variables. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request.
    """
    async with connected_client(connection) as client:
        await ep_subvars.delete_substitution_variables(client, application, variables, confirm=confirm)
    return "ok"


# ---- Approvals (Planning Units) --------------------------------------------------


@mcp.tool()
async def list_planning_units(
    connection: str,
    application: str,
    filter: dict[str, Any] | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List planning units owned by the caller. Read-only."""
    async with connected_client(connection) as client:
        return await ep_approvals.list_planning_units(client, application, filter=filter, offset=offset, limit=limit)


@mcp.tool()
async def get_available_actions(connection: str, application: str, pu_identifier: str) -> dict[str, Any]:
    """List valid next workflow actions for a planning unit. Read-only."""
    async with connected_client(connection) as client:
        return await ep_approvals.get_available_actions(client, application, pu_identifier)


@mcp.tool()
async def change_planning_unit_status(
    connection: str,
    application: str,
    puh_identifier: str,
    action: str,
    pm_members: list[str] | None = None,
    comments: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Planning Unit workflow action (promote/sign off/reject/etc.). DESTRUCTIVE.

    Call get_available_actions first to confirm the action is valid for the
    unit's current status. Never call with confirm=True on the same turn as
    the user's first request.
    """
    async with connected_client(connection) as client:
        return await ep_approvals.change_planning_unit_status(
            client, application, puh_identifier, action, pm_members=pm_members, comments=comments, confirm=confirm
        )


# ---- Smart Push / Data Management ------------------------------------------------


@mcp.tool()
async def run_pipeline(
    connection: str,
    pipeline_code: str,
    start_period: str | None = None,
    end_period: str | None = None,
    import_mode: str | None = None,
    export_mode: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Data Integration Pipeline by code. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request.
    """
    async with connected_client(connection) as client:
        return await ep_data_management.run_pipeline(
            client,
            pipeline_code,
            start_period=start_period,
            end_period=end_period,
            import_mode=import_mode,
            export_mode=export_mode,
            confirm=confirm,
        )


@mcp.tool()
async def run_data_rule(
    connection: str,
    rule_name: str,
    start_period: str | None = None,
    end_period: str | None = None,
    import_mode: str | None = None,
    export_mode: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Data Management data load rule. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request.
    """
    async with connected_client(connection) as client:
        return await ep_data_management.run_data_rule(
            client,
            rule_name,
            start_period=start_period,
            end_period=end_period,
            import_mode=import_mode,
            export_mode=export_mode,
            confirm=confirm,
        )


@mcp.tool()
async def run_batch(connection: str, batch_name: str, confirm: bool = False) -> dict[str, Any]:
    """Execute a batch of Data Management load rules together. DESTRUCTIVE."""
    async with connected_client(connection) as client:
        return await ep_data_management.run_batch(client, batch_name, confirm=confirm)


@mcp.tool()
async def get_data_management_job_status(connection: str, job_id: str) -> dict[str, Any]:
    """Poll a Data Management job's status. Read-only."""
    async with connected_client(connection) as client:
        return await ep_data_management.get_data_management_job_status(client, job_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
