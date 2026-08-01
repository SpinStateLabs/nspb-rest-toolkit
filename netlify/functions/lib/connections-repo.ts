/**
 * Per-customer connections, backed by Netlify DB (Postgres) -- the remote
 * surface's equivalent of the local surface's connections.yaml
 * (src/nspb_rest_toolkit/config.py). Same conceptual shape (slug,
 * display_name, base_url, auth_method, credential fields), different
 * storage: a row scoped to customer_id instead of a YAML mapping key,
 * credentials encrypted at rest (lib/crypto.ts) instead of resolved from
 * an env var at call time.
 */

import { getDatabase } from "@netlify/database";
import { encryptSecret, decryptSecret } from "./crypto.js";

export type AuthMethod = "basic" | "oauth2" | "bearer_token";

export interface ConnectionRecord {
  id: string;
  slug: string;
  displayName: string;
  baseUrl: string;
  authMethod: AuthMethod;
  defaultApplication: string | null;
}

/** Same field set as ConnectionRecord, plus decrypted credentials -- only ever used
 * inside a request handler to make the actual Oracle call, never returned in an
 * HTTP response. */
export interface ResolvedConnection extends ConnectionRecord {
  basicUsername: string | null;
  basicPassword: string | null;
  bearerToken: string | null;
  oauth2: {
    idcsBaseUrl: string;
    clientId: string;
    serviceInstanceId: string;
    allowRefresh: boolean;
    clientSecret: string | null;
  } | null;
}

export async function listConnections(customerId: string): Promise<ConnectionRecord[]> {
  const db = getDatabase();
  const rows = await db.sql`
    SELECT id, slug, display_name, base_url, auth_method, default_application
    FROM connections WHERE customer_id = ${customerId} ORDER BY slug
  `;
  return rows.map(toConnectionRecord);
}

export async function getResolvedConnection(
  customerId: string,
  slug: string
): Promise<ResolvedConnection | null> {
  const db = getDatabase();
  const rows = await db.sql`
    SELECT * FROM connections WHERE customer_id = ${customerId} AND slug = ${slug}
  `;
  if (rows.length === 0) return null;
  const row = rows[0] as Record<string, unknown>;

  return {
    ...toConnectionRecord(row),
    basicUsername: (row.basic_username as string | null) ?? null,
    basicPassword: row.basic_password_enc ? decryptSecret(row.basic_password_enc as Buffer) : null,
    bearerToken: row.bearer_token_enc ? decryptSecret(row.bearer_token_enc as Buffer) : null,
    oauth2:
      row.auth_method === "oauth2"
        ? {
            idcsBaseUrl: row.oauth2_idcs_base_url as string,
            clientId: row.oauth2_client_id as string,
            serviceInstanceId: row.oauth2_service_instance_id as string,
            allowRefresh: row.oauth2_allow_refresh as boolean,
            clientSecret: row.oauth2_client_secret_enc
              ? decryptSecret(row.oauth2_client_secret_enc as Buffer)
              : null,
          }
        : null,
  };
}

export interface ConnectionWrite {
  displayName: string;
  baseUrl: string;
  authMethod: AuthMethod;
  defaultApplication?: string | null;
  basicUsername?: string | null;
  basicPassword?: string | null;
  bearerToken?: string | null;
  oauth2?: {
    idcsBaseUrl: string;
    clientId: string;
    serviceInstanceId: string;
    allowRefresh: boolean;
    clientSecret?: string | null;
  } | null;
}

export async function upsertConnection(
  customerId: string,
  slug: string,
  body: ConnectionWrite
): Promise<ConnectionRecord> {
  const db = getDatabase();
  const o = body.oauth2 ?? null;
  const [row] = await db.sql`
    INSERT INTO connections (
      customer_id, slug, display_name, base_url, auth_method, default_application,
      basic_username, basic_password_enc, bearer_token_enc,
      oauth2_idcs_base_url, oauth2_client_id, oauth2_service_instance_id,
      oauth2_allow_refresh, oauth2_client_secret_enc
    ) VALUES (
      ${customerId}, ${slug}, ${body.displayName}, ${body.baseUrl}, ${body.authMethod},
      ${body.defaultApplication ?? null},
      ${body.basicUsername ?? null},
      ${body.basicPassword ? encryptSecret(body.basicPassword) : null},
      ${body.bearerToken ? encryptSecret(body.bearerToken) : null},
      ${o?.idcsBaseUrl ?? null}, ${o?.clientId ?? null}, ${o?.serviceInstanceId ?? null},
      ${o?.allowRefresh ?? true},
      ${o?.clientSecret ? encryptSecret(o.clientSecret) : null}
    )
    ON CONFLICT (customer_id, slug) DO UPDATE SET
      display_name = EXCLUDED.display_name,
      base_url = EXCLUDED.base_url,
      auth_method = EXCLUDED.auth_method,
      default_application = EXCLUDED.default_application,
      basic_username = EXCLUDED.basic_username,
      basic_password_enc = COALESCE(EXCLUDED.basic_password_enc, connections.basic_password_enc),
      bearer_token_enc = COALESCE(EXCLUDED.bearer_token_enc, connections.bearer_token_enc),
      oauth2_idcs_base_url = EXCLUDED.oauth2_idcs_base_url,
      oauth2_client_id = EXCLUDED.oauth2_client_id,
      oauth2_service_instance_id = EXCLUDED.oauth2_service_instance_id,
      oauth2_allow_refresh = EXCLUDED.oauth2_allow_refresh,
      oauth2_client_secret_enc = COALESCE(EXCLUDED.oauth2_client_secret_enc, connections.oauth2_client_secret_enc),
      updated_at = NOW()
    RETURNING id, slug, display_name, base_url, auth_method, default_application
  `;
  return toConnectionRecord(row);
}

export async function deleteConnection(customerId: string, slug: string): Promise<boolean> {
  const db = getDatabase();
  const rows = await db.sql`
    DELETE FROM connections WHERE customer_id = ${customerId} AND slug = ${slug} RETURNING id
  `;
  return rows.length > 0;
}

function toConnectionRecord(row: Record<string, unknown>): ConnectionRecord {
  return {
    id: row.id as string,
    slug: row.slug as string,
    displayName: row.display_name as string,
    baseUrl: row.base_url as string,
    authMethod: row.auth_method as AuthMethod,
    defaultApplication: (row.default_application as string | null) ?? null,
  };
}
