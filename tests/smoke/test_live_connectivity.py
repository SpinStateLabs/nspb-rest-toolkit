"""Optional live-tenant smoke tests. See conftest.py for required env vars.

Per this project's operational safety policy, do not run these against a
real customer tenant from a shared/hosted session -- run them from the
customer's own sanctioned environment with real credentials in env vars.
"""

from __future__ import annotations

import os

import pytest

from nspb_rest_toolkit.endpoints import applications, dimensions, forms, jobs

pytestmark = pytest.mark.asyncio


async def test_list_applications(smoke_client):
    result = await applications.list_applications(smoke_client)
    assert isinstance(result, list)
    assert len(result) > 0


async def test_list_dimensions(smoke_client, smoke_application, smoke_plantype):
    result = await dimensions.list_dimensions(smoke_client, smoke_application, smoke_plantype)
    assert isinstance(result, list)
    assert len(result) > 0


async def test_read_form(smoke_client, smoke_application, smoke_form):
    shape = await forms.read_form_grid_shape(smoke_client, smoke_application, smoke_form)
    assert shape is not None

    data = await forms.read_form_data(smoke_client, smoke_application, smoke_form)
    assert data is not None


@pytest.mark.skipif(
    not (os.environ.get("NSPB_SMOKE_ALLOW_DESTRUCTIVE") == "1" and os.environ.get("NSPB_SMOKE_BUSINESS_RULE")),
    reason="requires NSPB_SMOKE_ALLOW_DESTRUCTIVE=1 and NSPB_SMOKE_BUSINESS_RULE -- this test runs a real business rule",
)
async def test_run_business_rule_and_poll_job(smoke_client, smoke_application):
    rule_name = os.environ["NSPB_SMOKE_BUSINESS_RULE"]

    submission = await jobs.run_business_rule(smoke_client, smoke_application, rule_name, confirm=True)
    job_id = submission.get("jobId") or submission.get("jobID")
    assert job_id, f"job submission response had no jobId/jobID: {submission}"

    final_status = await jobs.poll_job_status(smoke_client, smoke_application, str(job_id))
    assert final_status.get("status") == "Completed"
