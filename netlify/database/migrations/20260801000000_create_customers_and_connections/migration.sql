-- Multi-customer SaaS schema for the remote MCP server (netlify/functions).
-- Separate from the local/stdio surface's connections.yaml -- that file
-- format and this table are two independent storage mechanisms for the
-- same underlying ConnectionConfig shape (see src/nspb_rest_toolkit/config.py).

CREATE TABLE customers (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  auth0_sub       TEXT UNIQUE NOT NULL,  -- Auth0's stable subject claim ("auth0|...", "google-oauth2|...", etc.)
  email           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE connections (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id           UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  slug                  TEXT NOT NULL,               -- unique per customer, not globally
  display_name          TEXT NOT NULL,
  base_url              TEXT NOT NULL,
  auth_method           TEXT NOT NULL CHECK (auth_method IN ('basic', 'oauth2', 'bearer_token')),
  default_application   TEXT,

  -- Basic auth: username plaintext (not a secret on its own), password
  -- encrypted. bearer_token: token encrypted. oauth2: non-secret identifiers
  -- plaintext, client_secret (if any) encrypted, live token cache stored
  -- separately (see oauth2_tokens below, mirrors the local surface's
  -- on-disk token cache but keyed by connection_id instead of a file path).
  -- Encryption: AES-256-GCM via CREDENTIALS_ENCRYPTION_KEY (Netlify env
  -- var, set once, never in this database) -- see netlify/functions/lib/crypto.ts.
  basic_username        TEXT,
  basic_password_enc    BYTEA,
  bearer_token_enc       BYTEA,

  oauth2_idcs_base_url          TEXT,
  oauth2_client_id              TEXT,
  oauth2_service_instance_id    TEXT,
  oauth2_allow_refresh          BOOLEAN NOT NULL DEFAULT TRUE,
  oauth2_client_secret_enc      BYTEA,

  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (customer_id, slug)
);

-- OAuth2 access/refresh token cache per connection -- equivalent to the
-- local surface's ~/.nspb-rest-toolkit/tokens/<slug>.json, but keyed by
-- connection_id since there's no per-customer filesystem here. Tokens are
-- credentials -- encrypted at rest the same way as everything else above.
CREATE TABLE oauth2_token_cache (
  connection_id       UUID PRIMARY KEY REFERENCES connections(id) ON DELETE CASCADE,
  access_token_enc    BYTEA NOT NULL,
  refresh_token_enc   BYTEA,
  expires_at           TIMESTAMPTZ NOT NULL,
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_connections_customer_id ON connections(customer_id);
