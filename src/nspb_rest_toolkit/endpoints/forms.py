"""Forms / data grids. Source: docs/endpoint-inventory.md section 5.

IMPORTANT -- this is NOT the symmetric form-ID-scoped read/write pair a
naive reading of Oracle's product docs might suggest. What's actually
documented:

- READ is form-ID-scoped: GET .../forms/{form}/data ("Export Form Data").
- WRITE is plan-type-scoped, not form-ID-scoped: POST
  .../plantypes/{plantype}/importdataslice ("Import Data Slice"). There is
  no PATCH .../forms/{form}/data endpoint in Oracle's current docs.
- There is no separate "get form definition" (structure-only) endpoint
  either. Oracle's own guidance for discovering a form's shape is to call
  Export Form Data with fields=gridInfo,pov first, then a second call for
  the full row/column data -- that's what read_form_grid_shape() does here.

Every write in this module MUST be preceded by a read_form_grid_shape() (or
read_form_data()) call in the SAME turn/session to learn the real POV/cell
shape before constructing a write body -- never guess a grid shape from
training data or a prior session. This is enforced by convention/docstring
here (there is no way to enforce it in the client chokepoint), so calling
LLMs must follow this sequencing explicitly. See docs/SKILL.md.
"""

from __future__ import annotations

from typing import Any

from ..client import EPMClient


async def read_form_grid_shape(client: EPMClient, application: str, form: str) -> dict[str, Any]:
    """Discover a form's POV/grid shape WITHOUT pulling full row/column data.

    Read-only. Call this FIRST, before read_form_data() or write_form_data(),
    for any form you have not already inspected in this session -- never
    guess the grid shape. Equivalent to Oracle's documented
    `fields=gridInfo,pov` discovery pattern.
    """
    resp = await client.call(
        "GET",
        f"/applications/{application}/forms/{form}/data",
        params={"fields": "gridInfo,pov"},
    )
    return resp.json()


async def read_form_data(
    client: EPMClient,
    application: str,
    form: str,
    *,
    page_member_list: str | None = None,
    display_member_as: str | None = None,
    force_start_expanded: bool | None = None,
    filter_members: str | None = None,
    fields: str | None = None,
) -> dict[str, Any]:
    """Read the full data grid (POV, rows, columns, cell values) for a Planning form.

    Read-only ("Export Form Data"). If you have not already called
    read_form_grid_shape() for this form in this session, call it first.
    """
    params: dict[str, Any] = {}
    if page_member_list is not None:
        params["pageMbrList"] = page_member_list
    if display_member_as is not None:
        params["displayMemberAs"] = display_member_as
    if force_start_expanded is not None:
        params["forceStartExpanded"] = force_start_expanded
    if filter_members is not None:
        params["filterMembers"] = filter_members
    if fields is not None:
        params["fields"] = fields

    resp = await client.call("GET", f"/applications/{application}/forms/{form}/data", params=params or None)
    return resp.json()


async def export_data_slice(
    client: EPMClient,
    application: str,
    plantype: str,
    grid_definition: dict[str, Any],
) -> dict[str, Any]:
    """Export a JSON data grid for an arbitrary region, not tied to a specific form ID.

    Read-only ("Export Data Slice"). Only cells the connection's credentials
    have read access to are returned. `grid_definition` shape must be
    learned from a real form/grid via read_form_grid_shape() or
    read_form_data() first, never guessed.
    """
    resp = await client.call(
        "POST",
        f"/applications/{application}/plantypes/{plantype}/exportdataslice",
        json=grid_definition,
    )
    return resp.json()


async def export_data(
    client: EPMClient,
    application: str,
    plantype: str,
    query_definition: dict[str, Any],
) -> dict[str, Any]:
    """Export data via an axis-based query (PovAxisDefinition/ColumnAxisDefinition/RowAxisDefinition).

    Read-only ("Export Data").
    """
    resp = await client.call(
        "POST",
        f"/applications/{application}/plantypes/{plantype}/exportdata",
        json=query_definition,
    )
    return resp.json()


async def write_form_data(
    client: EPMClient,
    application: str,
    plantype: str,
    grid: dict[str, Any],
    *,
    aggregate_essbase_data: bool | None = None,
    cell_notes_option: str | None = None,
    date_format: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Write a data grid (POV/columns/rows/cell values) into a plan type. DESTRUCTIVE.

    This is Oracle's plan-type-scoped "Import Data Slice" endpoint, used as
    the write-side counterpart to form data. `grid` MUST have been built
    from a real read_form_grid_shape() / read_form_data() call in this
    session -- never construct it from guesswork or a prior session's
    remembered shape, since forms can change. Never call this with
    confirm=True on the same turn as the user's first request to write
    data: describe exactly what will change (which cells, old vs. new
    values if known) and wait for explicit confirmation first.
    """
    body: dict[str, Any] = dict(grid)
    if aggregate_essbase_data is not None:
        body["aggregateEssbaseData"] = aggregate_essbase_data
    if cell_notes_option is not None:
        body["cellNotesOption"] = cell_notes_option
    if date_format is not None:
        body["dateFormat"] = date_format

    resp = await client.call(
        "POST",
        f"/applications/{application}/plantypes/{plantype}/importdataslice",
        json=body,
        destructive=True,
        confirm=confirm,
    )
    return resp.json()


async def clear_data_slice(
    client: EPMClient,
    application: str,
    plantype: str,
    grid_definition: dict[str, Any],
    *,
    clear_essbase_data: bool | None = None,
    clear_planning_data: bool | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Clear Planning/Essbase data for a region defined by grid_definition. DESTRUCTIVE.

    Never call with confirm=True on the same turn as the user's first
    request -- describe exactly what region/data will be cleared and wait
    for explicit confirmation.
    """
    body: dict[str, Any] = dict(grid_definition)
    if clear_essbase_data is not None:
        body["clearEssbaseData"] = clear_essbase_data
    if clear_planning_data is not None:
        body["clearPlanningData"] = clear_planning_data

    resp = await client.call(
        "POST",
        f"/applications/{application}/plantypes/{plantype}/cleardataslice",
        json=body,
        destructive=True,
        confirm=confirm,
    )
    return resp.json()
