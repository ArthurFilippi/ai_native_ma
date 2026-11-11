-- Schema of the Postgres store (D101). Same tables as the SQLite store; idempotent.
-- On Supabase: paste it in the SQL editor, or let PostgresStore.open() run it.
-- Row level security is not used: the API applies the access predicate in every query and
-- connects with a server-side role. Never expose these tables to the browser with the anon key.

CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deals (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS buyers (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (
  deal_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL,
  PRIMARY KEY (deal_id, user_id));
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, deal_id TEXT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (
  document_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL,
  PRIMARY KEY (document_id, page));
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, deal_id TEXT, entity_id TEXT,
  page INTEGER NOT NULL, char_start INTEGER NOT NULL, char_end INTEGER NOT NULL,
  text TEXT NOT NULL, kind TEXT NOT NULL, doc_type TEXT NOT NULL, published_on TEXT);
CREATE INDEX IF NOT EXISTS chunks_deal ON chunks (deal_id);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks (document_id);
CREATE INDEX IF NOT EXISTS documents_deal ON documents (deal_id);
CREATE INDEX IF NOT EXISTS memberships_user ON memberships (user_id);
