# Tenancy Policies

# Default policy

- allow_non_admin_global_read: false

# Notes

- Non-admin reads of `/root/.openclaw/agents/main/tenancy/global/**` are denied unless explicitly enabled above.
- Secrets must never be exposed in Discord replies or logs.
