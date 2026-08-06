---
name: Tailscale URL beats LAN IP for personal-device access
description: When exposing a dev service for the user's phone/laptop, prefer the Tailscale IP over the LAN IP
type: feedback
originSessionId: 92331e2a-f9df-4679-b734-d27cbe36271b
---
For dev services the user wants to reach from a phone or another personal device, **default to the Tailscale IP, not the LAN IP**. The user runs Tailscale on all his devices.

**Why:** Discovered in the weekend-escape-radar Phase 5 deploy — bound the Next.js dev server to `0.0.0.0:3000` and pointed him at `http://<dev-LAN-IP>:3000`. He couldn't reach it; Tailscale URL (`http://<tailscale-IP>:3000`) worked immediately. Likely AP isolation, a different SSID, or just being on cellular at the time.

**How to apply:** When suggesting how the user accesses something locally, lead with `tailscale ip` of the host (e.g. `100.x.x.x:3000`) rather than `192.168.x.x:3000`. Mention the LAN IP as a secondary option only. Server still binds `0.0.0.0` so both work; this is purely about which URL we hand him.
