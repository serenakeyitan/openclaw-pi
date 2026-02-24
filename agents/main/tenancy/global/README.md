# OpenClaw Tenancy (Discord)

This directory implements multi-tenant user isolation for the OpenClaw Discord agent.

## Managed Discord locations

- Guild `1470210055277121566`, Channel `1470210056086618194`
- Guild `1402227387005141154`, Channel `1470566790710169661`

The managed channel list is stored in `managed_channels.json`.

## Allowlist sync

Canonical allowlists are stored per managed channel:

- `/root/.openclaw/agents/main/tenancy/channel_<channel_id>_allowlist.json`

A periodic sync runs every 5 minutes. Because Discord cannot reliably list "who can view a channel" without extra scopes/intents, sync uses a safe approximation:

- Collect candidates from recent message authors in the channel and from existing allowlist entries.
- Verify each candidate by fetching:
  - guild member record
  - guild roles
  - channel permission overwrites
- Compute effective permissions and require `VIEW_CHANNEL`.
- Default to deny (mark `status=removed`) on any verification error.

Newly verified users are marked `active` and will have a per-user folder created.

## Folder layout

- Per-user root (canonical):
  - `/root/.openclaw/agents/main/tenancy/users/<user_id>/`
  - `sub-soul.md` (per-user memory/context)
  - `events.log` (append-only; secrets redacted)
  - `profile.json`

- Global (admin-only for writes):
  - `/root/.openclaw/agents/main/tenancy/global/`

- Server indexes (for later indexing; not authoritative):
  - `/root/.openclaw/agents/main/tenancy/servers/<guild_id>/`

## Permission rules

Admin user id: `878113709132771358`

Writes (hard deny):

- If actor user id is missing: deny.
- Non-admin may only write inside `/root/.openclaw/agents/main/tenancy/users/<actor_user_id>/`.
- Admin may write anywhere.

Reads (allowed but secret-protected):

- If actor user id is missing: deny.
- Non-admin may read under `/root/.openclaw/agents/main/tenancy/users/**`.
- Non-admin may not read sensitive paths (credentials/secrets/tokens/.env/etc) and any detected secret content is redacted (or denied if clearly credential-like).
- Non-admin reads under `/root/.openclaw/agents/main/tenancy/global/**` are denied unless `policies.md` enables it.
- Admin may read all files, but outputs to Discord are always redacted.

## Commands (mention-triggered)

These run only in managed channels, and only when the message mentions `@openclaw-pi`.

Admin:

- `tenancy sync-now [channel_id]`
- `tenancy list-users [channel_id]`
- `tenancy inspect <user_id>`
- `tenancy set-policy allow_non_admin_global_read true|false`

Non-admin:

- `me show`
- `me save <text>`
- `me reset`
- `user read <user_id> [file=sub-soul.md]`

## Per-user API keys (private)

Each user can store their own provider API keys (e.g. OpenAI) privately under:

- `/root/.openclaw/agents/main/tenancy/users/<user_id>/secrets/`

These files are never readable by non-admin users (even though non-admins can read other users' non-secret files).

### Setup flow (recommended)

1. In a managed channel (public), start setup:
   - `@openclaw-pi me setup openai`
2. The bot replies with a short setup code.
3. In a Discord DM to the bot (private), finish setup:
   - `setup openai <code> <your_api_key>`

### DM key management

In a Discord DM to the bot:

- `me api set openai <api_key>`
- `me api clear openai`
- `me api status`

### Key usage

- In managed Discord channels, if a user has `/secrets/openai_api_key`, it overrides the shared OpenAI credentials for that user's requests.
- For `web_search` (Brave), `/secrets/brave_api_key` overrides the shared Brave key in managed channels.

## Personal Email (Per User)

Per-user email access is set up via IMAP (Gmail app passwords supported). Credentials are stored per user under:

- `/root/.openclaw/agents/main/tenancy/users/<user_id>/secrets/email_imap.json`

Setup (Discord DM to the bot):

- `email setup gmail <your_email> <gmail_app_password>`

Test:

- `email inbox limit=5`
- `email read <id>`

Security:

- Email credentials are treated as secrets (not readable by non-admin users).
- DMs are accepted, but the bot will only run email setup/commands for users who are `active` in at least one managed channel allowlist.

## Safety

- Secrets are redacted from any Discord output.
- The implementation never prints tokens/credentials in logs.
