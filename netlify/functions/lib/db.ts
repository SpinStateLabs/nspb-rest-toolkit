/**
 * Plain Postgres access via `pg`, deliberately NOT `@netlify/database`.
 *
 * `@netlify/database`'s auto-provisioning (`createSiteDatabase`, run at
 * build time from the migrations in netlify/database/migrations/) turned
 * out to be discontinued for new databases as of this build -- Netlify's
 * own extension page: "This Netlify DB extension (powered by @netlify/neon)
 * has been discontinued. New database creation is no longer available
 * through this extension... An improved Netlify DB experience is coming
 * soon." Rather than depend on that mid-transition state, this connects to
 * a database provisioned directly (Neon or otherwise) via a manually-set
 * `DATABASE_URL` -- more portable, and not coupled to whichever Netlify DB
 * story ships next. The migration in netlify/database/migrations/ is still
 * the source of truth for the schema; since Netlify's auto-migration
 * doesn't run without their provisioning path, run it once by hand
 * (Neon's web SQL editor, or `psql "$DATABASE_URL" -f migration.sql`)
 * against whatever database DATABASE_URL points at.
 *
 * Exposes a `sql` tagged-template matching the shape connections-repo.ts
 * and auth.ts already use (mirroring @netlify/database's own `db.sql` API)
 * so switching providers again later stays a one-file change.
 */

import pg from "pg";

let pool: pg.Pool | null = null;

function getPool(): pg.Pool {
  if (!pool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error(
        "DATABASE_URL is not set. Provision a Postgres database (e.g. a Neon project) and set " +
          "its connection string as a Netlify environment variable named DATABASE_URL."
      );
    }
    pool = new pg.Pool({
      connectionString,
      // Neon (and most managed Postgres providers) require TLS; some Node
      // versions don't trust their intermediate CA by default. This matches
      // the widely-used pattern for connecting to Neon/Supabase-style
      // serverless Postgres from Node -- revisit if DATABASE_URL ever points
      // at a database where this laxer setting isn't appropriate.
      ssl: connectionString.includes("sslmode=require") ? { rejectUnauthorized: false } : undefined,
    });
  }
  return pool;
}

interface SqlRow {
  [column: string]: unknown;
}

async function sql(strings: TemplateStringsArray, ...values: unknown[]): Promise<SqlRow[]> {
  let text = "";
  strings.forEach((chunk, i) => {
    text += chunk;
    if (i < values.length) text += `$${i + 1}`;
  });
  const result = await getPool().query(text, values);
  return result.rows;
}

export function getDatabase(): { sql: typeof sql } {
  return { sql };
}
