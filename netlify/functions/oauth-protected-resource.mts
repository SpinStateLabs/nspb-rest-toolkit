/**
 * RFC 9728 Protected Resource Metadata -- tells an MCP client (claude.ai,
 * Claude Desktop's remote connector) which authorization server issues
 * tokens this server accepts, so it can drive the OAuth flow against Auth0
 * without being told that URL out of band.
 */
import type { Config } from "@netlify/functions";

export default async (req: Request) => {
  const domain = Netlify.env.get("AUTH0_DOMAIN");
  const siteUrl = Netlify.env.get("URL") ?? new URL(req.url).origin;

  if (!domain) {
    return new Response(JSON.stringify({ error: "server_misconfigured" }), {
      status: 500,
      headers: { "content-type": "application/json" },
    });
  }

  return new Response(
    JSON.stringify({
      resource: `${siteUrl}/mcp`,
      authorization_servers: [`https://${domain}/`],
    }),
    { headers: { "content-type": "application/json" } }
  );
};

export const config: Config = {
  path: "/.well-known/oauth-protected-resource",
};
