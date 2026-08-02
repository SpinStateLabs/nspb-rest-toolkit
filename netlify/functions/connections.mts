/**
 * Per-customer connections management API -- the remote surface's
 * equivalent of dashboard_api.py, backed by Netlify DB instead of
 * connections.yaml. OAuth-protected the same way as mcp.mts: every request
 * is scoped to the authenticated customer only.
 *
 *   GET    /api/connections           list this customer's connections (no credentials)
 *   POST   /api/connections/:slug     create
 *   PUT    /api/connections/:slug     update
 *   DELETE /api/connections/:slug     delete
 *
 * Never returns a decrypted credential -- ConnectionRecord (what these
 * routes read/write) has no credential fields at all; only
 * getResolvedConnection (lib/connections-repo.ts), used solely inside
 * mcp.mts's tool-call handling, ever decrypts one.
 */
import type { Config } from "@netlify/functions";
import { authenticate, AuthError } from "./lib/auth.js";
import { listConnections, upsertConnection, deleteConnection, type ConnectionWrite } from "./lib/connections-repo.js";
import { withCors, preflightResponse } from "./lib/cors.js";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export default async (req: Request) => {
  const res = await handle(req);
  return withCors(req, res);
};

async function handle(req: Request): Promise<Response> {
  if (req.method === "OPTIONS") {
    return preflightResponse(req);
  }

  let customer;
  try {
    customer = await authenticate(req);
  } catch (err) {
    if (err instanceof AuthError) return json({ error: err.message }, err.status);
    throw err;
  }

  const url = new URL(req.url);
  const slug = url.pathname.split("/").filter(Boolean).pop();
  const isCollection = url.pathname.replace(/\/+$/, "").endsWith("/connections");

  if (req.method === "GET" && isCollection) {
    const conns = await listConnections(customer.customerId);
    return json(conns);
  }

  if (!slug || isCollection) {
    return json({ error: "A connection slug is required in the path for this method." }, 400);
  }

  if (req.method === "POST" || req.method === "PUT") {
    let body: ConnectionWrite;
    try {
      body = await req.json();
    } catch {
      return json({ error: "Invalid JSON body." }, 400);
    }
    if (!body.displayName || !body.baseUrl || !body.authMethod) {
      return json({ error: "displayName, baseUrl, and authMethod are required." }, 400);
    }
    const conn = await upsertConnection(customer.customerId, slug, body);
    return json(conn, req.method === "POST" ? 201 : 200);
  }

  if (req.method === "DELETE") {
    const deleted = await deleteConnection(customer.customerId, slug);
    return new Response(null, { status: deleted ? 204 : 404 });
  }

  return json({ error: "Method not allowed." }, 405);
}

export const config: Config = {
  path: ["/api/connections", "/api/connections/*"],
};
