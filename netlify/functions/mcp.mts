/**
 * Remote MCP server -- Streamable HTTP transport (MCP spec 2025-03-26+),
 * the multi-customer SaaS surface for claude.ai and Claude Desktop's
 * remote-connector option. OAuth-protected: every request must carry a
 * valid Auth0-issued Bearer token (see lib/auth.ts) identifying which
 * customer is calling, so `tools/call` only ever touches that customer's
 * own stored connections (lib/connections-repo.ts) -- never another
 * customer's, and never a plaintext credential in a response.
 *
 * Tool set is intentionally a starting subset (list_connections,
 * list_applications) proving the full pipeline end to end -- see
 * lib/oracle-client.ts's docstring for how to extend it following the same
 * patterns already proven correct in the Python client this mirrors.
 *
 * This endpoint implements the simple (non-streaming) JSON-response mode of
 * Streamable HTTP -- every one of this server's current tools is a single
 * quick request/response with no server-initiated messages, so there's no
 * need for the SSE upgrade path yet.
 */
import type { Config } from "@netlify/functions";
import { authenticate, AuthError } from "./lib/auth.js";
import {
  listConnections,
  getResolvedConnection,
  upsertConnection,
  deleteConnection,
  type ConnectionWrite,
} from "./lib/connections-repo.js";
import { listApplications, OracleApiError } from "./lib/oracle-client.js";
import { corsGuard } from "./lib/cors.js";

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

function jsonRpcResult(id: JsonRpcRequest["id"], result: unknown): Response {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, result }), {
    headers: { "content-type": "application/json" },
  });
}

function jsonRpcError(id: JsonRpcRequest["id"], code: number, message: string, httpStatus = 200): Response {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }), {
    status: httpStatus,
    headers: { "content-type": "application/json" },
  });
}

const TOOLS = [
  {
    name: "list_connections",
    description: "List your configured Oracle EPM Cloud connections (slug + display name only -- no credentials).",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "list_applications",
    description: "List the Planning applications a connection's credentials are assigned to. Read-only.",
    inputSchema: {
      type: "object",
      properties: { connection: { type: "string", description: "Connection slug from list_connections." } },
      required: ["connection"],
    },
  },
  {
    name: "add_connection",
    description:
      "Create or update one of your Oracle EPM Cloud connections. Credentials are encrypted at rest " +
      "and never echoed back in any response. Calling this again with the same slug updates that " +
      "connection (a blank/omitted credential field leaves the previously stored one unchanged). " +
      "Only 'basic' and 'bearer_token' auth are usable for tool calls on this remote surface today " +
      "-- oauth2 connections aren't supported here yet, use the local desktop/CLI toolkit for those.",
    inputSchema: {
      type: "object",
      properties: {
        slug: { type: "string", description: "Short unique identifier, e.g. 'corp'. Lowercase, no spaces." },
        display_name: { type: "string", description: "Human-readable name shown in list_connections." },
        base_url: {
          type: "string",
          description: "Oracle EPM Planning base URL, e.g. https://your-tenant.epm.us-ashburn-1.ocs.oraclecloud.com",
        },
        auth_method: { type: "string", enum: ["basic", "bearer_token"] },
        username: { type: "string", description: "Required when auth_method is 'basic'." },
        password: { type: "string", description: "Required when auth_method is 'basic'." },
        bearer_token: { type: "string", description: "Required when auth_method is 'bearer_token'." },
        default_application: { type: "string", description: "Optional default Planning application name." },
      },
      required: ["slug", "display_name", "base_url", "auth_method"],
    },
  },
  {
    name: "delete_connection",
    description: "Permanently delete one of your Oracle EPM Cloud connections.",
    inputSchema: {
      type: "object",
      properties: { connection: { type: "string", description: "Connection slug from list_connections." } },
      required: ["connection"],
    },
  },
];

export default async (req: Request) => corsGuard(req, handle);

async function handle(req: Request): Promise<Response> {
  if (req.method !== "POST") {
    // Spec-legal: a Streamable HTTP server that doesn't offer a
    // server-initiated SSE stream MAY answer GET with 405 (MCP spec,
    // "Listening for Messages from the Server", point 3).
    return new Response("Method not allowed -- MCP Streamable HTTP uses POST.", { status: 405 });
  }

  let customer;
  try {
    customer = await authenticate(req);
  } catch (err) {
    if (err instanceof AuthError) {
      return new Response(JSON.stringify({ error: "unauthorized", message: err.message }), {
        status: err.status,
        headers: {
          "content-type": "application/json",
          // RFC 9728: point the client at the protected-resource metadata so it
          // knows to (re)start the OAuth flow with Auth0 instead of retrying blind.
          "WWW-Authenticate": `Bearer resource_metadata="${new URL(req.url).origin}/.well-known/oauth-protected-resource"`,
        },
      });
    }
    throw err;
  }

  let body: JsonRpcRequest;
  try {
    body = await req.json();
  } catch {
    return jsonRpcError(null, -32700, "Parse error: invalid JSON.", 400);
  }

  const { id = null, method, params = {} } = body;

  try {
    switch (method) {
      case "initialize":
        return jsonRpcResult(id, {
          protocolVersion: "2025-03-26",
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "nspb-rest-toolkit-remote", version: "0.1.0" },
        });

      case "notifications/initialized":
        // Notification, no id, no response body expected -- 202 is fine.
        return new Response(null, { status: 202 });

      case "tools/list":
        return jsonRpcResult(id, { tools: TOOLS });

      case "tools/call": {
        const toolName = params.name as string;
        const args = (params.arguments ?? {}) as Record<string, unknown>;

        if (toolName === "list_connections") {
          const conns = await listConnections(customer.customerId);
          return jsonRpcResult(id, {
            content: [{ type: "text", text: JSON.stringify(conns.map((c) => ({ slug: c.slug, display_name: c.displayName }))) }],
          });
        }

        if (toolName === "list_applications") {
          const slug = args.connection as string | undefined;
          if (!slug) return jsonRpcError(id, -32602, "Missing required argument 'connection'.");
          const conn = await getResolvedConnection(customer.customerId, slug);
          if (!conn) {
            return jsonRpcResult(id, {
              isError: true,
              content: [{ type: "text", text: `No connection named '${slug}'. Call list_connections first.` }],
            });
          }
          try {
            const apps = await listApplications(conn);
            return jsonRpcResult(id, { content: [{ type: "text", text: JSON.stringify(apps) }] });
          } catch (err) {
            const message = err instanceof OracleApiError ? err.message : String(err);
            return jsonRpcResult(id, { isError: true, content: [{ type: "text", text: message }] });
          }
        }

        if (toolName === "add_connection") {
          const slug = args.slug as string | undefined;
          const displayName = args.display_name as string | undefined;
          const baseUrl = args.base_url as string | undefined;
          const authMethod = args.auth_method as ConnectionWrite["authMethod"] | undefined;
          if (!slug || !displayName || !baseUrl || !authMethod) {
            return jsonRpcError(id, -32602, "slug, display_name, base_url, and auth_method are all required.");
          }
          if (authMethod !== "basic" && authMethod !== "bearer_token") {
            return jsonRpcResult(id, {
              isError: true,
              content: [{ type: "text", text: "auth_method must be 'basic' or 'bearer_token' on this remote surface." }],
            });
          }
          if (authMethod === "basic" && !(args.username && args.password)) {
            return jsonRpcResult(id, {
              isError: true,
              content: [{ type: "text", text: "auth_method 'basic' requires both 'username' and 'password'." }],
            });
          }
          if (authMethod === "bearer_token" && !args.bearer_token) {
            return jsonRpcResult(id, {
              isError: true,
              content: [{ type: "text", text: "auth_method 'bearer_token' requires 'bearer_token'." }],
            });
          }
          const write: ConnectionWrite = {
            displayName,
            baseUrl,
            authMethod,
            defaultApplication: (args.default_application as string | undefined) ?? null,
            basicUsername: (args.username as string | undefined) ?? null,
            basicPassword: (args.password as string | undefined) ?? null,
            bearerToken: (args.bearer_token as string | undefined) ?? null,
          };
          const conn = await upsertConnection(customer.customerId, slug, write);
          return jsonRpcResult(id, {
            content: [
              {
                type: "text",
                text: `Saved connection '${conn.slug}' (${conn.displayName}, ${conn.authMethod}). Credentials are encrypted at rest and were not echoed back.`,
              },
            ],
          });
        }

        if (toolName === "delete_connection") {
          const slug = args.connection as string | undefined;
          if (!slug) return jsonRpcError(id, -32602, "Missing required argument 'connection'.");
          const deleted = await deleteConnection(customer.customerId, slug);
          return jsonRpcResult(id, {
            isError: !deleted,
            content: [{ type: "text", text: deleted ? `Deleted connection '${slug}'.` : `No connection named '${slug}'.` }],
          });
        }

        return jsonRpcError(id, -32601, `Unknown tool '${toolName}'.`);
      }

      default:
        return jsonRpcError(id, -32601, `Method not found: '${method}'.`);
    }
  } catch (err) {
    // Never let a raw error (which could contain a decrypted credential in
    // a stack trace from lib/connections-repo.ts) reach the client.
    return jsonRpcError(id, -32603, "Internal error.", 500);
  }
}

export const config: Config = {
  path: "/mcp",
};
