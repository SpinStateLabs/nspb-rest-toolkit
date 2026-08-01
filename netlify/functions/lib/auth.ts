/**
 * Resource-server side of the OAuth 2.1 flow: verify an access token Auth0
 * issued, and map it to (or create) a row in `customers`.
 *
 * This function does NOT issue tokens or run the authorization/consent
 * flow -- that's Auth0's job entirely (hosted login, consent screen, token
 * endpoint). This only validates tokens presented to the MCP endpoint via
 * `Authorization: Bearer <token>`, using Auth0's published JWKS (no shared
 * secret between this server and Auth0 -- standard RS256 verification).
 *
 * Required env vars (set in Netlify, never in this repo):
 *   AUTH0_DOMAIN    e.g. "your-tenant.us.auth0.com" (no https://, no trailing slash)
 *   AUTH0_AUDIENCE  the API identifier configured in Auth0 for this resource server
 */

import { createRemoteJWKSet, jwtVerify, type JWTPayload } from "jose";
import { getDatabase } from "@netlify/database";

let jwks: ReturnType<typeof createRemoteJWKSet> | null = null;

function getJwks() {
  if (!jwks) {
    const domain = requireEnv("AUTH0_DOMAIN");
    jwks = createRemoteJWKSet(new URL(`https://${domain}/.well-known/jwks.json`));
  }
  return jwks;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set.`);
  return value;
}

export class AuthError extends Error {
  constructor(message: string, public status: number = 401) {
    super(message);
  }
}

export interface AuthenticatedCustomer {
  customerId: string;
  auth0Sub: string;
}

/**
 * Verify the Authorization header and return the corresponding customer,
 * creating a `customers` row on first sight of a new Auth0 subject
 * (Auth0 is the source of truth for identity; we just mirror the subject
 * into our own DB the first time it shows up, so `connections` has a
 * stable local foreign key that doesn't change if Auth0's own internal
 * user ID representation ever does).
 */
export async function authenticate(req: Request): Promise<AuthenticatedCustomer> {
  const header = req.headers.get("authorization");
  if (!header?.startsWith("Bearer ")) {
    throw new AuthError("Missing or malformed Authorization header.", 401);
  }
  const token = header.slice("Bearer ".length);

  const audience = requireEnv("AUTH0_AUDIENCE");
  const domain = requireEnv("AUTH0_DOMAIN");

  let payload: JWTPayload;
  try {
    const result = await jwtVerify(token, getJwks(), {
      issuer: `https://${domain}/`,
      audience,
    });
    payload = result.payload;
  } catch (err) {
    // Never echo the raw token back in an error -- it's a credential.
    throw new AuthError(
      `Token verification failed: ${err instanceof Error ? err.message : "unknown error"}`,
      401
    );
  }

  const sub = payload.sub;
  if (!sub) {
    throw new AuthError("Token has no 'sub' claim.", 401);
  }

  const db = getDatabase();
  const existing = await db.sql`SELECT id FROM customers WHERE auth0_sub = ${sub}`;
  if (existing.length > 0) {
    return { customerId: existing[0].id as string, auth0Sub: sub };
  }

  const email = typeof payload.email === "string" ? payload.email : null;
  const [created] = await db.sql`
    INSERT INTO customers (auth0_sub, email) VALUES (${sub}, ${email})
    ON CONFLICT (auth0_sub) DO UPDATE SET updated_at = NOW()
    RETURNING id
  `;
  return { customerId: created.id as string, auth0Sub: sub };
}
