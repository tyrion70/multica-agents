---
name: Netbox URL
description: Correct netbox URL is thebox2.cinternal.com, not netbox.chosts.io
type: reference
originSessionId: 49c8f697-fba4-45d4-9fc7-93f696d11ebc
---
Netbox is at `https://thebox2.cinternal.com/` — NOT `netbox.chosts.io`.

API token from GCP: `gcloud secrets versions access latest --secret="netbox-terraform-rw-access-key" --project="gitlab-412312"`

API usage: `curl -sk -H "Authorization: Token $TOKEN" "https://thebox2.cinternal.com/api/..."`
