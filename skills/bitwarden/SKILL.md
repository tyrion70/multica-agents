---
name: bitwarden
description: Read, create, or update secrets in Peter's self-hosted Bitwarden/Vaultwarden vault. Use whenever a task requires looking up a credential (SSH key, API token, password) OR storing one. Folder choice (private / shared / company) is required on every write — ASK if the project context doesn't make it obvious.
---

# Bitwarden / Vaultwarden access

The vault is **self-hosted Vaultwarden** at `https://192.168.19.11:8443`, account `peter@tyrion.nl`. Reach it from any host on the homelab LAN or via Tailscale. The Bitwarden CLI (`bw`) is the primary interface — it speaks to Vaultwarden the same way it speaks to bitwarden.com.

## Step 0 — unlock

The vault is locked by default. To unlock, source the bootstrap env and use `--passwordenv`:

```bash
set -a
. ~/.claude/secrets/bw-bootstrap.env
set +a
export NODE_TLS_REJECT_UNAUTHORIZED=0          # self-signed cert
export BW_SESSION=$(bw unlock --raw --passwordenv BW_PASSWORD 2>/dev/null)
```

After that, every `bw …` call needs `--session "$BW_SESSION"`.

**Important** — the bootstrap file `~/.claude/secrets/bw-bootstrap.env` is gitignored and contains:
- `BW_CLIENTID` / `BW_CLIENTSECRET` — used by `bw login` for an unattended login (already done; vault is logged in, just locked)
- `BW_PASSWORD` — the master password, used by `bw unlock --passwordenv BW_PASSWORD`
- `BW_HOST` — the server URL

**Never echo / print / log / save / display `$BW_PASSWORD`, the session token, or item values** in conversation, logs, or stored files. The bootstrap env file is the secret-of-secrets — anyone with it can decrypt everything. Don't copy it. Don't include its contents in code reviews. Don't paste it into a chat.

**The `NODE_TLS_REJECT_UNAUTHORIZED=0`** is required because the Vaultwarden cert is self-signed. Without it, `bw sync` and `bw create` will fail with "self-signed certificate". The lock/unlock works without it because those operations are local-only.

## Folder model — pick the right one on EVERY write

The vault is organized into three top-level folders. Items have a `folderId` field; setting it correctly is part of saving a secret, not an afterthought.

| Folder | Folder ID | Use for |
|---|---|---|
| **`private`** | `d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5` | Personal projects (homelab, family stuff, tyrion70 GitHub repos, personal SaaS like Tremor / ESS / Weekend-Escape-Radar). The user is the only consumer. |
| **`shared`** | `263e645f-08b4-4b6b-b5d9-3d6fe994b415` | Cross-cutting credentials that span personal AND family use (home Wi-Fi PSK, guest portal password, shared streaming accounts). |
| **`company`** | `fa7ec305-d8c0-4603-bcb4-248cf5be04ae` | ChainLayer work (GitLab, GCP, k8s, chainlayer.io accounts, Linear, Slack tokens, anything tied to gitlab.com/chainlayer or `peter@chainlayer.io`). |

### Picking the folder

Work backward from "who else might consume this credential":

- ChainLayer Linear issue, chainlayer/* GitLab repo, kubectl context, Tailscale tag `tag:chainlayer-*` → **`company`**
- tyrion70/* GitHub repo, homelab (proxmox/proxmox2/proxmox3/proxmox4), UniFi/Mikrotik/Hetzner, ess-ai-planner, tremor, weekend-escape-radar → **`private`**
- WLAN PSK, family-facing service, anything Sandra/the kids also use → **`shared`**

### If the context isn't obvious — ASK

Don't guess. The user has been explicit: when unsure, ask which folder. A wrong folder isn't a security incident, but it's annoying to clean up. A 5-second `AskUserQuestion` is much cheaper than a silent default.

Trigger words to ask about:
- A credential could plausibly serve both work and personal (a generic email, a shared cloud account, an account at chainlayer.io that's actually personal-billed)
- The project the user is currently `cd`'d into doesn't map cleanly to one of the three
- The credential is for an external SaaS where the boundary depends on who's paying

## Lookup — common patterns

```bash
# By name (substring match, case-insensitive)
bw list items --session "$BW_SESSION" --search "github"

# Just the names (terse)
bw list items --session "$BW_SESSION" --search "github" \
  | python3 -c "import json,sys; [print(x['name']) for x in json.load(sys.stdin)]"

# A specific custom field on a specific item
bw get item <id-or-exact-name> --session "$BW_SESSION" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
print({f['name']: f['value'] for f in d.get('fields',[])}.get('UNIFI_API_KEY'))"

# All items in a given folder
bw list items --session "$BW_SESSION" --folderid d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5
```

For ad-hoc shell use, prefer `bw get password <name>` and `bw get username <name>` — these print *just the value*, suitable for command substitution:

```bash
PASS=$(bw get password "Mikrotik CRS812-8DS-2DQ-2DDQ — homelab switch" --session "$BW_SESSION")
```

Note: `bw get password` works on Login items. For SecureNotes with hidden custom fields (the pattern we use for multi-value secrets), parse `bw get item` JSON as above.

## Write — SecureNote pattern (multi-value)

For credentials that come in groups (API URL + API key + multiple shared secrets), a single SecureNote with hidden custom fields keeps them together. This is what the UniFi and Mikrotik items use.

```bash
python3 <<'PY' | bw encode > /tmp/bw-new.b64
import json
item = {
  "organizationId": None, "collectionIds": None,
  "folderId": "d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5",   # private — pick the right folder ID
  "type": 2,                                              # 2 = SecureNote
  "name": "<descriptive name with model + role>",
  "notes": "Multi-line description. Include source file path if any, the host/IP, and any DON'Ts.",
  "favorite": False,
  "fields": [
    {"name": "FIELD_1", "value": "<value>", "type": 1},   # type 1 = hidden
    {"name": "FIELD_2", "value": "<value>", "type": 1}
  ],
  "secureNote": {"type": 0}
}
print(json.dumps(item))
PY
bw create item "$(cat /tmp/bw-new.b64)" --session "$BW_SESSION"
bw sync --session "$BW_SESSION"
rm -f /tmp/bw-new.b64
```

## Write — Login pattern (single-target SSH/HTTP cred)

For a credential that's literally "go to URL X, type username Y, password Z" (an SSH login, a web app), use a Login item:

```bash
python3 <<'PY' | bw encode > /tmp/bw-login.b64
import json
item = {
  "organizationId": None, "collectionIds": None,
  "folderId": "d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5",
  "type": 1,                                              # 1 = Login
  "name": "<host or service name>",
  "notes": "",
  "login": {
    "username": "<user>",
    "password": "<password>",
    "uris": [{"match": None, "uri": "ssh://<host>"}],
    "totp": None
  }
}
print(json.dumps(item))
PY
bw create item "$(cat /tmp/bw-login.b64)" --session "$BW_SESSION"
bw sync --session "$BW_SESSION"
rm -f /tmp/bw-login.b64
```

## Update an existing item

```bash
# Get current item JSON
bw get item "<id-or-exact-name>" --session "$BW_SESSION" > /tmp/bw-item.json

# Edit the JSON (e.g. via python -c) — change folderId, add a field, etc.

# Encode and push back
cat /tmp/bw-item.json | bw encode | xargs -I{} bw edit item <item-id> {} --session "$BW_SESSION"
bw sync --session "$BW_SESSION"
rm -f /tmp/bw-item.json
```

The `bw edit item` shape mirrors `bw create item` — pass the full edited item JSON, not just the diff.

## Move an existing item into a folder

```bash
ITEM_ID="<id>"
FOLDER_ID="d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5"   # private
bw get item "$ITEM_ID" --session "$BW_SESSION" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); d['folderId']='$FOLDER_ID'; print(json.dumps(d))" \
  | bw encode \
  | xargs -I{} bw edit item "$ITEM_ID" {} --session "$BW_SESSION"
bw sync --session "$BW_SESSION"
```

## Don'ts

1. **Don't surface secret values to the user** — they already have them; echoing them back is unnecessary exposure. After a write, confirm with the item name + field NAMES only, never values.
2. **Don't write a credential without a folderId.** "No Folder" is the default; it's the wrong choice and means somebody (you, future-you, the user) will move it later.
3. **Don't `bw sync` without `NODE_TLS_REJECT_UNAUTHORIZED=0`** — it fails. The error is "self-signed certificate".
4. **Don't reuse `BW_SESSION` across processes** — it's a per-process secret. Each Bash session unlocks fresh.
5. **Don't commit `~/.claude/secrets/`** to any repo. It's already in `.gitignore`; double-check before any `git add -A`.
6. **Don't leave temp `*.b64` or `*.json` files** of unlocked item data sitting in `/tmp` — `rm -f` them at the end of each write block. Even though `/tmp` is wiped on reboot, between now and then they're plaintext.
7. **Don't write a credential to BW that you found in chat-history or in a file you'll then delete** — the chat may be cached/exported; check whether the user pasted it explicitly or it leaked into context.

## Health checks

```bash
# Is bw logged in?
bw status --session "$BW_SESSION" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])"
# → "unlocked"

# How many items total
bw list items --session "$BW_SESSION" | python3 -c "import json,sys; print(len(json.load(sys.stdin)),'items')"

# How many items per folder
bw list items --session "$BW_SESSION" | python3 -c "
import json,sys,collections
items=json.load(sys.stdin)
fmap={'d72b99f9-0a18-4bf8-8eac-8b3b9c66fcc5':'private',
      '263e645f-08b4-4b6b-b5d9-3d6fe994b415':'shared',
      'fa7ec305-d8c0-4603-bcb4-248cf5be04ae':'company',
      None:'(no folder)'}
c=collections.Counter(fmap.get(i.get('folderId'),'(?)') for i in items)
for k,v in c.most_common(): print(f'  {k}: {v}')"
```

## Linking from other skills

When a sibling skill (e.g. `homelab`, `company-k8s`) needs a credential, it should reference the BW item by name + folder, not embed the value. Example from `homelab`:

> **Mikrotik**: BW item "Mikrotik CRS812-8DS-2DQ-2DDQ — homelab switch" (`MIKROTIK_HOST`, `MIKROTIK_USER`, `MIKROTIK_PASSWORD`)

That way a future read happens from BW (current, rotated values), not from a stale skill file.

### Known self-rotating item

The group PAT item **"ChainLayer · GitLab — group PAT"** (`company` folder) is a
**SecureNote** whose token lives in a **hidden custom field named `PAT`** (parse
the `fields` array — there is no `login.password`). It carries the `self_rotate`
GitLab scope. An agent that finds the token expired or near-expiry can rotate it
via GitLab's `POST /personal_access_tokens/self/rotate` endpoint and **write the
new value back** into this item's `PAT` field + `bw sync`. See the **`git-mr`**
skill for the full procedure and the proactive-only caveat.
