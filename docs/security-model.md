# Jyzrox Security Model

Canonical record of the authorization architecture and its **accepted trade-offs**.
Read this before any change that touches auth, media delivery, or a "security
hardening" of a hot path. If a proposed change contradicts a decision recorded
here, the decision must be revisited explicitly (update this file in the same
PR) — do not silently override it.

Threat model: a self-hosted, single-household deployment. Users are
semi-trusted family members / collaborators. Explicit **non-goals**: heavyweight
RBAC (groups, custom roles), CSP-style hard isolation between users, and
timing/side-channel resistance.

---

## The three authorization layers

| Layer | Mechanism | Defined in |
|---|---|---|
| 1. Global roles | `admin(3) > member(2) > viewer(1)`, hierarchical; `require_role()` dependency factory | `core/auth.py` |
| 2. Per-gallery ACL | ownership + `GalleryPermission` rows (+ `visibility=public`, unowned/system galleries) | `core/auth.py` |
| 3. Capability URLs | possession of a high-entropy token/SHA + a valid session grants access | `services/media_authz.py`, `routers/gallery_management.py` |

### Layer 2 is read/write asymmetric — by design

- **Read** — `gallery_access_filter(auth)`: admin sees all; others see own +
  unowned/system + public + **any** `GalleryPermission` row (including
  read-only collaborators, `can_edit=false`).
- **Write** — `has_gallery_write_access(...)`: admin / owner / unowned, or a
  `GalleryPermission` row **with `can_edit=true`**.

Consequence: an endpoint that mutates a gallery or its images and gates only on
visibility (`gallery_access_filter` or `_gallery()` lookups) lets read-only
collaborators write. This exact bug shipped twice (`804d5b4` image processing,
`b621ad4` manual tags). Every mutation path must call
`has_gallery_write_access()`.

Both helpers live only in `core/auth.py`. Never reimplement the visibility
logic elsewhere — join back to `gallery_access_filter()` (as
`services/media_authz.py` does).

---

## Accepted trade-offs (do not "fix" these without revisiting)

### BR-006 — CAS/thumb URLs are authenticated capabilities

`/media/cas/<sha>` and `/media/thumbs/<sha>` require a valid session (nginx
`auth_request`) but are **not** resolved back through gallery ACLs per request.
The high-entropy SHA-256 is the capability; guessing it is not a viable attack,
and anyone who can derive the SHA already possesses the content.

- Path-addressed `/media/libraries/<path>` **does** get full gallery-ACL checks
  (paths are guessable).
- `/media/image/` (imgproxy) validates that the decoded source stays inside
  `local:///cas/` / `local:///thumbs/` (prevents arbitrary `/data` reads,
  audit #67) but does not resolve the SHA through ACLs.
- A future strict multi-user mode may restore per-gallery CAS ACLs via signed
  URLs or an ACL epoch. It is **not** the default hot path.

Executable spec (these tests fail if the fast path is re-gated):

- `backend/tests/test_media_authz.py::test_media_authz_direct_cas_uses_authenticated_capability_semantics`
- `backend/tests/test_media_authz.py::test_auth_check_cas_path_uses_session_only`
- `backend/tests/test_media_authz.py::test_media_authz_imgproxy_cas_source_allowed_without_gallery_lookup`

### Bounded revocation delay

- nginx `auth_request` result is cached **30s** (`proxy_cache_valid`): a revoked
  session can read media for at most 30 more seconds.
- Role changes propagate to live Redis sessions immediately
  (`routers/users.py`); if Redis is unavailable, all of the user's sessions are
  deleted to force re-login.
- Service-worker media/page caches are cleared on logout. An ACL-only change
  *without* logout is intentionally not an immediate revocation boundary for
  content-addressed capability URLs.

### Share links

Anonymous access by token only: `secrets.token_urlsafe(32)`, stored as SHA-256
hash (DB leak ≠ link leak), default 7-day / max 1-year expiry, revocable,
optional R18 filter. Shared images are served exclusively through
`shares/{token}/images/{id}` with a gallery-membership check — the token never
widens into a session.

---

## Hot-path rule (lesson of `91af972` → reverted by `1093995`/`e91bd03`)

A module-boundary hardening added per-request gallery-ACL lookups to CAS/thumb
delivery and disabled service-worker media caching. Post-incident measurement
showed the server was never the bottleneck (60 cold thumbnails at concurrency
48 = 0.48s; one `auth/check` = 2ms): both regressions came from disabling
client/edge caching for an authorization property that content-addressed
capability URLs do not need.

Therefore, for any change touching these hot paths —

- `/media/cas/`, `/media/thumbs/`, `/media/image/` delivery (nginx locations,
  `routers/auth.py::check_auth`, `services/media_authz.py`)
- service-worker media caching (`pwa/public/sw.template.js`)

— the PR must include:

1. A statement of which decision in this file it upholds or revisits.
2. Before/after measurements when adding any per-request work (DB/Redis
   round-trips, subrequests, cache disablement). "More secure" is not a
   justification by itself; name the concrete attack the change stops.

---

## Fail-closed contract

`services/media_authz.py` returns `False` on any internal error (DB, decode):
a bug in the authorization layer may deny access but can never leak it. Keep
this property in any refactor.
