/**
 * Minimal Oracle EPM Cloud Planning REST client -- Basic Auth only, read-only
 * operations only, for now. This is a deliberate initial subset (proving the
 * full remote pipeline: OAuth-authenticated request -> decrypt stored
 * customer credentials -> call Oracle -> return MCP result) rather than a
 * complete port of src/nspb_rest_toolkit/client.py's ~30 endpoints. Expand
 * this module following the same patterns already proven correct (and
 * live-tested against a real tenant) in the Python client:
 *   - unwrap_items(): Oracle wraps list responses in {"items": [...]}, not
 *     a bare array (see client.py's unwrap_items and its docstring).
 *   - JSON POST bodies need `Content-Type: application/json; charset=utf-8`
 *     explicitly (httpx/fetch defaults omit the charset; Oracle's own
 *     responses always include one).
 *   - oauth2 and bearer_token auth methods aren't implemented here yet --
 *     ResolvedConnection.oauth2/.bearerToken exist in the schema but
 *     get_client() below only handles auth_method: "basic" so far.
 */

import type { ResolvedConnection } from "./connections-repo.js";

export class OracleApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export function planningBaseUrl(conn: ResolvedConnection): string {
  return `${conn.baseUrl.replace(/\/$/, "")}/HyperionPlanning/rest/v3`;
}

function authHeader(conn: ResolvedConnection): string {
  if (conn.authMethod === "basic") {
    if (!conn.basicUsername || !conn.basicPassword) {
      throw new OracleApiError(
        `Connection '${conn.slug}' is auth_method=basic but has no stored username/password.`,
        400
      );
    }
    const token = Buffer.from(`${conn.basicUsername}:${conn.basicPassword}`).toString("base64");
    return `Basic ${token}`;
  }
  if (conn.authMethod === "bearer_token") {
    if (!conn.bearerToken) {
      throw new OracleApiError(`Connection '${conn.slug}' is auth_method=bearer_token but has no stored token.`, 400);
    }
    return `Bearer ${conn.bearerToken}`;
  }
  throw new OracleApiError(
    `auth_method=oauth2 isn't implemented on the remote surface yet -- use 'basic' or 'bearer_token' for now.`,
    501
  );
}

/** Oracle wraps collection responses in {"items": [...], "links": [...]}, not a bare array. */
function unwrapItems(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object" && Array.isArray((payload as any).items)) {
    return (payload as any).items;
  }
  return [];
}

async function call(conn: ResolvedConnection, path: string): Promise<unknown> {
  const resp = await fetch(`${planningBaseUrl(conn)}${path}`, {
    headers: { Authorization: authHeader(conn), Accept: "application/json" },
  });
  const text = await resp.text();
  if (!resp.ok) {
    throw new OracleApiError(`Oracle returned HTTP ${resp.status} for GET ${path}: ${text.slice(0, 500)}`, resp.status);
  }
  return text ? JSON.parse(text) : null;
}

export async function listApplications(conn: ResolvedConnection): Promise<unknown[]> {
  return unwrapItems(await call(conn, "/applications"));
}
