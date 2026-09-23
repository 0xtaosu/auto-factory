# MCP and independent API keys

The user selected option A: an administrator issues independent keys. Backend is
owned by the primary agent; frontend continues to be implemented by Grok.

## Scope and implementation plan

1. Add a SQLite credential store alongside existing job storage. Random API keys
   have a name, prefix, scopes, optional expiry, creation/last-use/revocation times.
   Store only SHA256 digests of high-entropy secrets. Show a newly issued API key
   once. Keys cannot issue other keys, create sessions, or administer credentials.
2. Bootstrap a random administrator login secret into a local mode-0600 file on
   first application start (or accept INVENTORY_ADMIN_TOKEN from environment).
   Never print secrets in server logs. Login creates an opaque, hashed, 8-hour
   HttpOnly SameSite=Strict session cookie. Administrative endpoints accept only
   admin sessions; no unauthenticated key creation. Use an explicit trusted-origin
   allowlist for browser credential requests and mutations. HTTPS is required for
   remote use; cookie Secure is configurable for reverse-proxy deployments.
3. Protect every existing /api/activity endpoint. A browser admin session has all
   project permissions. Independent bearer keys can have activity:read and
   optionally activity:analyze. All keys share this single project's datasets;
   this is not tenant or per-user data isolation. Existing jobs remain available.
4. Add an official SDK Streamable HTTP endpoint at /mcp, with bearer API keys only.
   Tools: list_jobs, get_job, get_overview, list_assessments, explain_material,
   get_export_info. These tools are read-only and use existing services. Large
   exports return metadata and an authenticated REST path, not a secret-bearing URL
   or a huge inline RDF result. The first version supports clients with custom
   Authorization headers; it does not claim OAuth login interoperability.
5. Add browser login and API-key management using the contract below. Provide a
   generic MCP connection configuration with a placeholder key and editable URL.
   Never persist full API keys/admin login tokens in localStorage or URLs.
6. Test login, cookie/logout, digest storage, invalid/expired/revoked keys, scopes,
   admin-only issuance, origin checks, authenticated REST and MCP initialize/list/
   call. Verify UI creation/revocation and preservation of existing activity UI.

## Frontend contract

All fetch calls use credentials: 'include'. Existing inventory endpoints now return
401 when unauthenticated. ApiError should expose status for the app to show login
again when an admin session expires. Never turn 401 into an empty inventory result.

- POST /api/auth/login JSON {token:string} -> {role:'admin', expires_at:ISO}; sets cookie.
- GET /api/auth/session -> {role:'admin', expires_at:ISO}; 401 without valid session.
- POST /api/auth/logout -> {ok:true}; invalidates cookie/session.
- GET /api/admin/keys -> {items:[KeyInfo]}.
- POST /api/admin/keys JSON {name:string, scopes:['activity:read'], expires_at:ISO|null}
  -> {key:string, info:KeyInfo}. `activity:analyze` may additionally be selected;
  activity:read is required. Expiry must be in future. Name 1..80 chars.
- DELETE /api/admin/keys/{key_id} -> {ok:true}; revoke is idempotent.
- GET /api/admin/mcp -> {endpoint_path:'/mcp', transport:'streamable-http',
  auth:'bearer-api-key', tools:[{name,description}], scopes:[{name,description}],
  data_access:'All keys access this project data; no per-key dataset isolation.'}.
- Errors use {detail:string} and status 401/403/422/429 as appropriate.

KeyInfo = {key_id, name, prefix, scopes:[string], created_at, expires_at:null|ISO,
last_used_at:null|ISO, revoked_at:null|ISO, status:'active'|'expired'|'revoked'}.
Full keys are returned only by create; neither list nor session endpoints reveal
them. The UI must clearly show/copy the newly created key, dismiss it, and explain
that it cannot be retrieved later. Keep it only in component memory.

## UI scope for Grok

Wrap the existing inventory application with authenticated admin login, then add a
navigation entry 'MCP / API Keys'. Preserve existing data analysis behavior. Login
asks for the administrator login token. Describe retrieval generically as the
server's locally generated administrator secret or configured admin token; do not
embed any real credential. Key page includes create/name/read + optional analyze/
optional expiry, last used/status, revoke confirmation, one-time secret reveal,
MCP URL and copyable generic mcpServers JSON with Authorization Bearer placeholder.
Endpoint default uses VITE_API_BASE in dev (http://localhost:8000/mcp), otherwise
same origin /mcp. For remotely shared config allow editing the URL, no automatic
localhost substitutions that claim remote clients can access this machine.
Do not imply API keys support every OAuth-only MCP client. Mention custom-header
client support. No new UI framework. Do not modify backend or root config/docs.
