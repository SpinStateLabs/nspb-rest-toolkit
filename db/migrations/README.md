# Database migrations

This directory is intentionally **not** `netlify/database/migrations/` -- that
path is Netlify's own auto-migration convention for `@netlify/database`'s
now-discontinued auto-provisioning (`createSiteDatabase`); Netlify's build
system scans for that exact path and tries to run it regardless of whether
`@netlify/database` is actually a dependency, which fails the build. This
project connects to Postgres directly instead (see
[`netlify/functions/lib/db.ts`](../../netlify/functions/lib/db.ts)) and runs
migrations by hand.

To apply a migration against whatever database `DATABASE_URL` points at:

```bash
psql "$DATABASE_URL" -f db/migrations/<migration-dir>/migration.sql
```

or paste the file's contents into your Postgres provider's web SQL editor
(e.g. Neon's SQL Editor) if you don't have `psql` installed locally.

Migrations are applied in directory-name order (`NNNN..._description/`) and
are not currently auto-tracked -- keep a mental note of which have been
applied to which database, or add a `schema_migrations` tracking table if
this needs to scale beyond one operator running them by hand.
