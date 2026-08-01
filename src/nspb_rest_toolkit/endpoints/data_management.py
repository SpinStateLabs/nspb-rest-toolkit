"""Smart Push / Data Management. Source: docs/endpoint-inventory.md section 12.

Separate API family -- base path `aif/rest/v1`, not HyperionPlanning or
interop. family="data_management" on every call() here.

IMPORTANT: no REST endpoint or Planning jobType literally named "Smart
Push" was found in Oracle's current docs. Smart Push is inferred to route
through this same Data Management job-submission endpoint (it is a Data
Management/Data Integration feature invoked from the same Job Console as
pipelines and data rules), but that specific mapping is NOT textually
confirmed -- treat run_pipeline()/run_data_rule() as confirmed Data
Management operations, and do not tell a customer "this runs Smart Push"
without flagging that the connection is inferred, not documented.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient


async def run_pipeline(
    client: EPMClient,
    pipeline_code: str,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    import_mode: str | None = None,
    export_mode: str | None = None,
    attach_logs: bool | None = None,
    send_mail: bool | None = None,
    send_to: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Data Integration Pipeline by code. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request -- describe which pipeline and period range will run and wait
    for explicit confirmation.
    """
    variables: dict[str, Any] = {}
    if start_period is not None:
        variables["STARTPERIOD"] = start_period
    if end_period is not None:
        variables["ENDPERIOD"] = end_period
    if import_mode is not None:
        variables["IMPORTMODE"] = import_mode
    if export_mode is not None:
        variables["EXPORTMODE"] = export_mode
    if attach_logs is not None:
        variables["ATTACH_LOGS"] = attach_logs
    if send_mail is not None:
        variables["SEND_MAIL"] = send_mail
    if send_to is not None:
        variables["SEND_TO"] = send_to

    body: dict[str, Any] = {"jobType": "pipeline", "jobName": pipeline_code}
    if variables:
        body["variables"] = variables

    resp = await client.call(
        "POST", "/jobs", family="data_management", json=body, destructive=True, confirm=confirm
    )
    return resp.json()


async def run_data_rule(
    client: EPMClient,
    rule_name: str,
    *,
    start_period: str | None = None,
    end_period: str | None = None,
    import_mode: str | None = None,
    export_mode: str | None = None,
    file_name: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute a Data Management data load rule. DESTRUCTIVE.

    `import_mode` is one of APPEND/REPLACE/RECALCULATE/NONE. Never call with
    confirm=True on the same turn as the user's first request.
    """
    body: dict[str, Any] = {"jobType": "DATARULE", "jobName": rule_name}
    if start_period is not None:
        body["startPeriod"] = start_period
    if end_period is not None:
        body["endPeriod"] = end_period
    if import_mode is not None:
        body["importMode"] = import_mode
    if export_mode is not None:
        body["exportMode"] = export_mode
    if file_name is not None:
        body["fileName"] = file_name

    resp = await client.call(
        "POST", "/jobs", family="data_management", json=body, destructive=True, confirm=confirm
    )
    return resp.json()


async def run_batch(client: EPMClient, batch_name: str, *, confirm: bool = False) -> dict[str, Any]:
    """Execute a batch of Data Management load rules together. DESTRUCTIVE.

    Path/body confirmed only via Oracle's TOC title ("Running Batch Rules")
    during Phase 0 research, not independently re-fetched in full -- verify
    against a live tenant response before relying on this in production.
    """
    body = {"jobType": "BATCH", "jobName": batch_name}
    resp = await client.call(
        "POST", "/jobs", family="data_management", json=body, destructive=True, confirm=confirm
    )
    return resp.json()


async def get_data_management_job_status(client: EPMClient, job_id: str) -> dict[str, Any]:
    """Poll a Data Management job's status. Read-only.

    Exact status-resource path confirmed only via TOC title
    ("Retrieve Job Status") during Phase 0 research -- verify against a
    live tenant response before relying on this in production.
    """
    resp = await client.call("GET", f"/jobs/{job_id}", family="data_management")
    return resp.json()
