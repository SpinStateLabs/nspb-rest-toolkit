"""Jobs -- generic submit/status plus typed job types.

Source: docs/endpoint-inventory.md sections 6-7. All typed jobs share one
submission resource: POST .../applications/{application}/jobs with body
{"jobType": ..., "jobName": ..., "parameters": {...}}.

Note on job type names vs. the original task brief: Oracle's current docs do
not use the literal strings CLEAR_DATA or REFRESH_DATABASE -- the confirmed
current equivalents are CLEAR_CUBE and CUBE_REFRESH. JOB_TYPE_TAGS below
uses the confirmed names.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient

# jobType -> "read" | "destructive", from docs/endpoint-inventory.md section 7.
JOB_TYPE_TAGS: dict[str, str] = {
    "RULES": "destructive",
    "RULESET": "destructive",
    "PLAN_TYPE_MAP": "destructive",
    "IMPORT_DATA": "destructive",
    "EXPORT_DATA": "read",
    "IMPORT_METADATA": "destructive",
    "EXPORT_METADATA": "read",
    "CUBE_REFRESH": "destructive",
    "CLEAR_CUBE": "destructive",
    "ADMINISTRATION_MODE": "destructive",
    "COMPACT_CUBE": "destructive",
    "RESTRUCTURE_CUBE": "destructive",
    "MERGE_DATA_SLICES": "destructive",
    "OPTIMIZE_AGGREGATION": "destructive",
    "IMPORT_SECURITY": "destructive",
    "EXPORT_SECURITY": "read",
    "EXPORT_AUDIT": "read",
    "EXPORT_JOB_CONSOLE": "read",
    "SORT_MEMBERS": "destructive",
    "IMPORT_EXCHANGE_RATES": "destructive",
    "AUTO_PREDICT": "destructive",
    "IMPORT_CELL_LEVEL_SECURITY": "destructive",
    "EXPORT_CELL_LEVEL_SECURITY": "read",
    "IMPORT_VALID_INTERSECTIONS": "destructive",
    "EXPORT_VALID_INTERSECTIONS": "read",
    "REPORT_BURSTING": "destructive",
    "EXPORT_LIBRARY_DOCUMENTS": "read",
    "IMPORT_LIBRARY_DOCUMENTS": "destructive",
    "DELETE_LIBRARY_DOCUMENTS": "destructive",
    "CONFIGURE_OGL_SERVER": "destructive",
}


async def submit_job(
    client: EPMClient,
    application: str,
    job_type: str,
    job_name: str,
    *,
    parameters: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Submit any Planning job by jobType. See JOB_TYPE_TAGS for the read/destructive tag.

    Most job types are DESTRUCTIVE (they run business rules, import data or
    metadata, refresh/restructure cubes, etc.) -- never call with
    confirm=True on the same turn as the user's first request; describe
    what the job will do and wait for explicit confirmation. An unrecognized
    job_type is treated as destructive by default (fail closed) unless
    confirm=True is explicitly passed, since a job this toolkit doesn't
    recognize might mutate the application.

    Returns the initial job-submission response (typically containing a
    jobId) -- call poll_job_status() to wait for completion.
    """
    tag = JOB_TYPE_TAGS.get(job_type, "destructive")
    destructive = tag == "destructive"

    body: dict[str, Any] = {"jobType": job_type, "jobName": job_name}
    if parameters:
        body["parameters"] = parameters

    resp = await client.call(
        "POST",
        f"/applications/{application}/jobs",
        json=body,
        destructive=destructive,
        confirm=confirm,
    )
    return resp.json()


async def get_job_status(client: EPMClient, application: str, job_id: str) -> dict[str, Any]:
    """Retrieve the current status of a submitted job by ID. Read-only.

    status codes: -1 in progress, 0 success, 1 error, 2 cancel pending,
    3 cancelled, 4 invalid parameter.
    """
    resp = await client.call("GET", f"/applications/{application}/jobs/{job_id}")
    return resp.json()


async def poll_job_status(
    client: EPMClient,
    application: str,
    job_id: str,
    *,
    poll_interval: float = 3.0,
    timeout: float = 900.0,
) -> dict[str, Any]:
    """Poll a submitted job to a terminal state. Read-only.

    Uses the Planning named-state contract via EPMClient.poll_job -- raises
    EPMJobError on an error/invalid terminal state or timeout.
    """
    return await client.poll_job(
        "planning",
        f"/applications/{application}/jobs/{job_id}",
        poll_interval=poll_interval,
        timeout=timeout,
    )


async def run_business_rule(
    client: EPMClient,
    application: str,
    rule_name: str,
    *,
    runtime_prompts: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Launch a Planning business rule by exact name. DESTRUCTIVE.

    Thin convenience wrapper over submit_job(jobType="RULES"). Never call
    with confirm=True on the same turn as the user's first request to run a
    rule -- describe which rule and what it does, wait for explicit
    confirmation, then call again with confirm=True.
    """
    return await submit_job(
        client, application, "RULES", rule_name, parameters=runtime_prompts, confirm=confirm
    )
