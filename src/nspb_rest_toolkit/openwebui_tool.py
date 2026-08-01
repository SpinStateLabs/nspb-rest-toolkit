"""
title: NSPB REST Toolkit
description: Direct REST toolkit for Oracle EPM Cloud Planning & Budgeting (NSPB) -- applications, dimensions, forms, jobs, migration/LCM, security, substitution variables, approvals, and Data Management.
author: Spin State Labs
version: 0.1.0
requirements: nspb-rest-toolkit
"""

# Paste this file into Open WebUI: Workspace -> Tools -> + -> paste. Open
# WebUI reads the `requirements:` line above and pip-installs
# nspb-rest-toolkit automatically, so this file stays a thin adapter over
# the real package rather than a re-implementation -- see
# src/nspb_rest_toolkit/endpoints/ for the actual REST logic and
# docs/SKILL.md for full safety guidance.
#
# SAFETY (read this before calling any method below that says DESTRUCTIVE):
# Reads are always safe. Destructive methods require confirm=True.
# NEVER call a destructive method with confirm=True on the same turn as the
# user's first request, regardless of how the request is phrased --
# describe exactly what will change, wait for the user's explicit
# confirmation in a following message, THEN call again with confirm=True.
# For form-data writes specifically: ALWAYS call read_form_grid_shape (or
# read_form_data) for the target form/plantype first, in this same
# conversation, before building a write_form_data grid -- never guess a
# grid shape from a prior session.

from __future__ import annotations

import contextlib
import json
from typing import Any

from pydantic import BaseModel, Field

from nspb_rest_toolkit.client import EPMClient
from nspb_rest_toolkit.config import load_config
from nspb_rest_toolkit.endpoints import applications as ep_applications
from nspb_rest_toolkit.endpoints import approvals as ep_approvals
from nspb_rest_toolkit.endpoints import data_management as ep_data_management
from nspb_rest_toolkit.endpoints import dimensions as ep_dimensions
from nspb_rest_toolkit.endpoints import forms as ep_forms
from nspb_rest_toolkit.endpoints import jobs as ep_jobs
from nspb_rest_toolkit.endpoints import migration as ep_migration
from nspb_rest_toolkit.endpoints import security as ep_security
from nspb_rest_toolkit.endpoints import substitution_variables as ep_subvars


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


class Tools:
    class Valves(BaseModel):
        config_path: str = Field(
            default="connections.yaml",
            description="Path (on the Open WebUI host) to the multi-tenant connections.yaml file.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    @contextlib.asynccontextmanager
    async def _client(self, connection: str):
        cfg = load_config(self.valves.config_path)
        conn = cfg.get(connection)
        client = EPMClient(conn)
        try:
            yield client
        finally:
            await client.aclose()

    def list_connections(self) -> str:
        """List configured customer connections (slug + display name only -- no credentials)."""
        cfg = load_config(self.valves.config_path)
        return _render([{"slug": slug, "display_name": conn.display_name} for slug, conn in cfg.connections.items()])

    # ---- Applications -------------------------------------------------------

    async def list_applications(self, connection: str) -> str:
        """List the Planning applications the connection's credentials are assigned to. Read-only.

        :param connection: Connection slug from connections.yaml.
        """
        async with self._client(connection) as client:
            return _render(await ep_applications.list_applications(client))

    async def get_application_summary(self, connection: str, application: str) -> str:
        """Get an automation-oriented summary of an application's structure. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        """
        async with self._client(connection) as client:
            return _render(await ep_applications.get_application_summary(client, application))

    # ---- Dimensions / Members -------------------------------------------------

    async def list_plan_types(self, connection: str, application: str) -> str:
        """List plan types (cubes) for an application. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        """
        async with self._client(connection) as client:
            return _render(await ep_dimensions.list_plan_types(client, application))

    async def list_dimensions(self, connection: str, application: str, plantype: str) -> str:
        """List dimensions associated with a plan type. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param plantype: Plan type (cube) name.
        """
        async with self._client(connection) as client:
            return _render(await ep_dimensions.list_dimensions(client, application, plantype))

    async def get_dimension(self, connection: str, application: str, plantype: str, dimension: str) -> str:
        """Get a dimension's hierarchy/details. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param plantype: Plan type (cube) name.
        :param dimension: Dimension name.
        """
        async with self._client(connection) as client:
            return _render(await ep_dimensions.get_dimension(client, application, plantype, dimension))

    async def get_member(self, connection: str, application: str, dimension: str, member: str) -> str:
        """Get a single member's properties (parent, data storage, data type, etc). Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param dimension: Dimension name.
        :param member: Member name.
        """
        async with self._client(connection) as client:
            return _render(await ep_dimensions.get_member(client, application, dimension, member))

    async def add_member(
        self,
        connection: str,
        application: str,
        dimension: str,
        member_name: str,
        parent_name: str,
        confirm: bool = False,
    ) -> str:
        """Add a new member under a parent in a dimension outline. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request -- describe the change and wait for explicit confirmation.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param dimension: Dimension name.
        :param member_name: New member's name.
        :param parent_name: Parent member's name (must already allow dynamic children).
        :param confirm: Must be True to actually perform the write.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_dimensions.add_member(client, application, dimension, member_name, parent_name, confirm=confirm)
            )

    # ---- Forms ---------------------------------------------------------------

    async def read_form_grid_shape(self, connection: str, application: str, form: str) -> str:
        """Discover a form's POV/grid shape without pulling full data. Read-only.

        ALWAYS call this before write_form_data for any form not already
        inspected in this conversation -- never guess a grid shape.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param form: Form name or ID.
        """
        async with self._client(connection) as client:
            return _render(await ep_forms.read_form_grid_shape(client, application, form))

    async def read_form_data(
        self,
        connection: str,
        application: str,
        form: str,
        page_member_list: str | None = None,
        display_member_as: str | None = None,
        filter_members: str | None = None,
    ) -> str:
        """Read the full data grid (POV, rows, columns, cell values) for a Planning form. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param form: Form name or ID.
        :param page_member_list: Optional page-axis member selection.
        :param display_member_as: Optional member display mode.
        :param filter_members: Optional member filter.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_forms.read_form_data(
                    client,
                    application,
                    form,
                    page_member_list=page_member_list,
                    display_member_as=display_member_as,
                    filter_members=filter_members,
                )
            )

    async def write_form_data(
        self,
        connection: str,
        application: str,
        plantype: str,
        grid: dict[str, Any],
        confirm: bool = False,
    ) -> str:
        """Write a data grid into a plan type (form-data write). DESTRUCTIVE.

        `grid` MUST come from a read_form_grid_shape/read_form_data call
        made earlier in THIS conversation -- never guess the shape. Never
        call with confirm=True on the same turn as the user's first request
        to write data -- describe exactly what will change and wait for
        explicit confirmation, then call again with confirm=True.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param plantype: Plan type (cube) name -- writes are plan-type-scoped, not form-ID-scoped.
        :param grid: POV/columns/rows/cell-value body, shaped exactly like a prior read_form_data() response.
        :param confirm: Must be True to actually perform the write.
        """
        async with self._client(connection) as client:
            return _render(await ep_forms.write_form_data(client, application, plantype, grid, confirm=confirm))

    async def clear_data_slice(
        self,
        connection: str,
        application: str,
        plantype: str,
        grid_definition: dict[str, Any],
        confirm: bool = False,
    ) -> str:
        """Clear Planning/Essbase data for a region. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param plantype: Plan type (cube) name.
        :param grid_definition: Region to clear.
        :param confirm: Must be True to actually perform the clear.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_forms.clear_data_slice(client, application, plantype, grid_definition, confirm=confirm)
            )

    # ---- Jobs -------------------------------------------------------------------

    async def submit_job(
        self,
        connection: str,
        application: str,
        job_type: str,
        job_name: str,
        parameters: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str:
        """Submit a Planning job by jobType. Most job types are DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request -- describe what the job will do and wait for explicit
        confirmation.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param job_type: e.g. RULES, IMPORT_DATA, EXPORT_DATA, IMPORT_METADATA, EXPORT_METADATA, CUBE_REFRESH, CLEAR_CUBE.
        :param job_name: Job name (e.g. exact business rule name for RULES).
        :param parameters: Optional job-type-specific parameters.
        :param confirm: Must be True to actually run a destructive job type.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_jobs.submit_job(client, application, job_type, job_name, parameters=parameters, confirm=confirm)
            )

    async def get_job_status(self, connection: str, application: str, job_id: str) -> str:
        """Retrieve the current status of a submitted job. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param job_id: Job ID returned by submit_job.
        """
        async with self._client(connection) as client:
            return _render(await ep_jobs.get_job_status(client, application, job_id))

    async def poll_job_status(self, connection: str, application: str, job_id: str) -> str:
        """Poll a submitted job to a terminal state (Completed/Error/Invalid). Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param job_id: Job ID returned by submit_job.
        """
        async with self._client(connection) as client:
            return _render(await ep_jobs.poll_job_status(client, application, job_id))

    async def run_business_rule(
        self,
        connection: str,
        application: str,
        rule_name: str,
        runtime_prompts: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str:
        """Launch a Planning business rule by exact name. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request -- describe which rule and what it does, wait for explicit
        confirmation, then call again with confirm=True.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param rule_name: Exact business rule name.
        :param runtime_prompts: Optional runtime prompt values.
        :param confirm: Must be True to actually run the rule.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_jobs.run_business_rule(client, application, rule_name, runtime_prompts=runtime_prompts, confirm=confirm)
            )

    # ---- Migration / LCM -------------------------------------------------------------

    async def export_snapshot(self, connection: str, snapshot_name: str, confirm: bool = False) -> str:
        """Trigger a repeat export of a Migration artifact snapshot. DESTRUCTIVE.

        :param connection: Connection slug from connections.yaml.
        :param snapshot_name: Snapshot name.
        :param confirm: Must be True to actually run the export.
        """
        async with self._client(connection) as client:
            return _render(await ep_migration.export_snapshot(client, snapshot_name, confirm=confirm))

    async def import_snapshot(
        self,
        connection: str,
        snapshot_name: str,
        import_users: bool | None = None,
        confirm: bool = False,
    ) -> str:
        """Import the contents of an application snapshot -- overwrites application content. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request -- describe exactly what will be overwritten and wait for
        explicit confirmation.

        :param connection: Connection slug from connections.yaml.
        :param snapshot_name: Snapshot name.
        :param import_users: Also import users (requires Identity Domain Administrator role).
        :param confirm: Must be True to actually perform the import.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_migration.import_snapshot(client, snapshot_name, import_users=import_users, confirm=confirm)
            )

    async def get_migration_status(self, connection: str) -> str:
        """Get migration (export/import) history. Read-only.

        :param connection: Connection slug from connections.yaml.
        """
        async with self._client(connection) as client:
            return _render(await ep_migration.get_migration_status(client))

    async def poll_migration_job(self, connection: str, job_id: str) -> str:
        """Poll a migration job to a terminal state. Read-only.

        A returned status of 1 ("completed with issues") is a valid
        terminal state, not an error -- call get_migration_job_task_details
        next to see what happened.

        :param connection: Connection slug from connections.yaml.
        :param job_id: Migration job ID.
        """
        async with self._client(connection) as client:
            return _render(await ep_migration.poll_migration_job(client, job_id))

    async def get_migration_job_task_details(self, connection: str, job_id: str, task_id: str) -> str:
        """Get detailed task-level messages for a migration job. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param job_id: Migration job ID.
        :param task_id: Task ID within the migration job.
        """
        async with self._client(connection) as client:
            return _render(await ep_migration.get_migration_job_task_details(client, job_id, task_id))

    # ---- Access Permissions (security, job-based) ---------------------------------

    async def import_security(
        self,
        connection: str,
        application: str,
        file_name: str,
        clear_all: bool | None = None,
        confirm: bool = False,
    ) -> str:
        """Import ACL/security records from a CSV file in the repository. DESTRUCTIVE.

        clear_all=True wipes existing permissions first -- call that out
        explicitly when describing this action. Never call with
        confirm=True on the same turn as the user's first request.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param file_name: CSV file name already in the Planning repository.
        :param clear_all: Wipe existing permissions before importing.
        :param confirm: Must be True to actually perform the import.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_security.import_security(client, application, file_name, clear_all=clear_all, confirm=confirm)
            )

    async def export_security(self, connection: str, application: str, file_name: str) -> str:
        """Export ACL/security records to a CSV file. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param file_name: Target CSV file name in the Planning repository.
        """
        async with self._client(connection) as client:
            return _render(await ep_security.export_security(client, application, file_name))

    # ---- Substitution Variables -----------------------------------------------------

    async def list_substitution_variables(self, connection: str, application: str) -> str:
        """Get all substitution variables for an application. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        """
        async with self._client(connection) as client:
            return _render(await ep_subvars.list_substitution_variables(client, application))

    async def set_substitution_variables(
        self, connection: str, application: str, variables: list[dict[str, Any]], confirm: bool = False
    ) -> str:
        """Create or update substitution variables. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request -- list the names/values that will change and wait for
        explicit confirmation.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param variables: List of {"name", "value", "planType"} ("ALL" or a specific plan type).
        :param confirm: Must be True to actually write.
        """
        async with self._client(connection) as client:
            await ep_subvars.set_substitution_variables(client, application, variables, confirm=confirm)
            return "ok"

    async def delete_substitution_variables(
        self, connection: str, application: str, variables: list[dict[str, Any]], confirm: bool = False
    ) -> str:
        """Delete substitution variables. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param variables: List of {"name", "planType"} identifying items to delete.
        :param confirm: Must be True to actually delete.
        """
        async with self._client(connection) as client:
            await ep_subvars.delete_substitution_variables(client, application, variables, confirm=confirm)
            return "ok"

    # ---- Approvals (Planning Units) --------------------------------------------------

    async def list_planning_units(self, connection: str, application: str) -> str:
        """List planning units owned by the caller. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        """
        async with self._client(connection) as client:
            return _render(await ep_approvals.list_planning_units(client, application))

    async def get_available_actions(self, connection: str, application: str, pu_identifier: str) -> str:
        """List valid next workflow actions for a planning unit. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param pu_identifier: Planning unit identifier.
        """
        async with self._client(connection) as client:
            return _render(await ep_approvals.get_available_actions(client, application, pu_identifier))

    async def change_planning_unit_status(
        self,
        connection: str,
        application: str,
        puh_identifier: str,
        action: str,
        comments: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Execute a Planning Unit workflow action (promote/sign off/reject/etc). DESTRUCTIVE.

        Call get_available_actions first to confirm the action is valid for
        the unit's current status. Never call with confirm=True on the same
        turn as the user's first request.

        :param connection: Connection slug from connections.yaml.
        :param application: Planning application name.
        :param puh_identifier: Planning unit hierarchy identifier.
        :param action: One of PROMOTE, SIGN_OFF, APPROVE, DELEGATE, TAKE_OWNERSHIP, ORIGINATE, FREEZE.
        :param comments: Optional comment to attach to the action.
        :param confirm: Must be True to actually perform the action.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_approvals.change_planning_unit_status(
                    client, application, puh_identifier, action, comments=comments, confirm=confirm
                )
            )

    # ---- Smart Push / Data Management ------------------------------------------------

    async def run_pipeline(
        self,
        connection: str,
        pipeline_code: str,
        start_period: str | None = None,
        end_period: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Execute a Data Integration Pipeline by code. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request.

        :param connection: Connection slug from connections.yaml.
        :param pipeline_code: Pipeline code.
        :param start_period: Optional start period.
        :param end_period: Optional end period.
        :param confirm: Must be True to actually run the pipeline.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_data_management.run_pipeline(
                    client, pipeline_code, start_period=start_period, end_period=end_period, confirm=confirm
                )
            )

    async def run_data_rule(
        self,
        connection: str,
        rule_name: str,
        start_period: str | None = None,
        end_period: str | None = None,
        import_mode: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Execute a Data Management data load rule. DESTRUCTIVE.

        Never call with confirm=True on the same turn as the user's first
        request.

        :param connection: Connection slug from connections.yaml.
        :param rule_name: Data load rule name.
        :param start_period: Optional start period.
        :param end_period: Optional end period.
        :param import_mode: One of APPEND, REPLACE, RECALCULATE, NONE.
        :param confirm: Must be True to actually run the rule.
        """
        async with self._client(connection) as client:
            return _render(
                await ep_data_management.run_data_rule(
                    client,
                    rule_name,
                    start_period=start_period,
                    end_period=end_period,
                    import_mode=import_mode,
                    confirm=confirm,
                )
            )

    async def get_data_management_job_status(self, connection: str, job_id: str) -> str:
        """Poll a Data Management job's status. Read-only.

        :param connection: Connection slug from connections.yaml.
        :param job_id: Data Management job ID.
        """
        async with self._client(connection) as client:
            return _render(await ep_data_management.get_data_management_job_status(client, job_id))
