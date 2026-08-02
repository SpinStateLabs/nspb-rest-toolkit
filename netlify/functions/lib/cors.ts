/**
 * CORS support for the browser-based MCP clients (claude.ai runs the
 * connector in-browser, not from a native app) -- without these headers,
 * the browser blocks the response before any application code ever sees it,
 * which surfaces to the user as a generic "couldn't connect" error with no
 * further detail, since a CORS failure never reaches our error handling.
 */
const ALLOW_HEADERS = "authorization, content-type, mcp-protocol-version, mcp-session-id";
const ALLOW_METHODS = "GET, POST, DELETE, OPTIONS";

export function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin");
  return {
    "Access-Control-Allow-Origin": origin ?? "*",
    "Access-Control-Allow-Methods": ALLOW_METHODS,
    "Access-Control-Allow-Headers": ALLOW_HEADERS,
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

export function withCors(req: Request, res: Response): Response {
  const headers = new Headers(res.headers);
  for (const [key, value] of Object.entries(corsHeaders(req))) headers.set(key, value);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

export function preflightResponse(req: Request): Response {
  return new Response(null, { status: 204, headers: corsHeaders(req) });
}

/**
 * Guarantees every response -- including one from a completely unexpected
 * crash (a DB outage, a bad env var) -- carries CORS headers. Without this,
 * an uncaught exception skips withCors() entirely and Netlify's own default
 * error page has no Access-Control-Allow-Origin header, which the browser
 * reports as a bare network failure with no detail: exactly what surfaced
 * to the user as claude.ai's generic "Couldn't connect to the server."
 */
export async function corsGuard(req: Request, handler: (req: Request) => Promise<Response>): Promise<Response> {
  if (req.method === "OPTIONS") {
    return preflightResponse(req);
  }
  try {
    const res = await handler(req);
    return withCors(req, res);
  } catch (err) {
    console.error("Unhandled error in function handler:", err);
    return withCors(
      req,
      new Response(JSON.stringify({ error: "internal_error", message: "Internal server error." }), {
        status: 500,
        headers: { "content-type": "application/json" },
      })
    );
  }
}
