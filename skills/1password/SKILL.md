---
name: 1password
description: Read secrets from the 1Password vault via the `op` CLI. Use whenever a task requires a credential that now lives in 1Password (currently the new GitLab PAT) instead of Bitwarden. During the migration BOTH vaults hold real secrets — if a credential isn't found in Bitwarden, check 1Password before concluding it doesn't exist.
---

