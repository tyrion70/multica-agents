---
name: homelab-vpn-vm
description: "Homelab NordVPN gateway VM (102 \"vpn\" on proxmox4, 192.168.16.163) — architecture + the three gotchas that broke it on 2026-06-11"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5f5dff3c-3a2c-49ae-9e4d-63edd8f50f9f
---

VM 102 `vpn` on proxmox4 (192.168.16.163 uplink on ens19; eth0 = 192.168.100.10/24 client LAN). It is the gateway/DNS for VPN clients: dnsmasq (DHCP-server at 192.168.100.1 hands out .10 as router) forwards all DNS to NordVPN 103.86.96.100; wg-quick@wg0 = NordVPN WireGuard; iptables kill-switch (FORWARD eth0→wg0 only) + DNS-leak protection (OUTPUT dpt:53 DROP unless out wg0 or lo) persisted via iptables-persistent /etc/iptables/rules.v4.

Gotchas found 2026-06-11:
- **eth0 must stay static** (`/etc/netplan/60-vpn-eth0.yaml`). With dhcp4 it leases from its own client network and installs a default route via its own IP → blackholes all egress → tunnel + DNS dead. This was the original "DNS broken" cause.
- **`netplan apply` flushes wg-quick's policy-routing rules** (pref 32764/32765) → traffic silently leaks out the home WAN instead of the tunnel. Always `systemctl restart wg-quick@wg0` after netplan apply on this box.
- **Boot clock skew poisons WireGuard anti-replay**: VM had Proxmox `localtime: 1` → booted +2h (CEST offset); after a handshake with a future timestamp, NTP stepped the clock back and the NordVPN server silently dropped all new handshakes (timestamp older than last seen). Fix applied: `qm set 102 --localtime 0`. Recovery trick: switch Endpoint to another NordVPN server — all NL servers share the same WG pubkey, only the IP changes; per-server timestamp state resets. Server list: `curl https://api.nordvpn.com/v1/servers/recommendations?filters[servers_technologies][identifier]=wireguard_udp&limit=4`.

NordVPN resolver returns 192.0.0.88 for Google domains — their DNS behavior, not a fault. wg0.conf backup at /etc/wireguard/wg0.conf.bak-2026-06-11. Related: [[homelab-cluster]]

## Per-country HTTP proxy fleet (added 2026-06-11, for Tremor earthquakes app)

Docker + gluetun, one container per country, each an HTTP proxy bound to `192.168.16.163:<port>` (LAN-only). Lives in `/opt/vpn-proxy/` (`docker-compose.yml` is GENERATED — edit `gen-compose.sh` MAP and re-run, never hand-edit the yaml). WG key reused from wg0.conf into `/opt/vpn-proxy/.env` (chmod 600). Reference doc: `~/claude/projects/vpn-proxy/README.md`.

Ports→country (Tremor TYR tickets): 8881 cu→US (TYR-84), 8882 bd→Bangladesh (TYR-97), 8883 mm→Myanmar (TYR-98), 8884 cn→Myanmar exit (TYR-99, see below), 8885 lb→Lebanon (TYR-89), 8886 sa→UAE (TYR-91), 8887 az→Azerbaijan (TYR-70), 8888 do→Dominican Rep (TYR-82), 8889 iq→Iraq (TYR-87), 8890 jo→Jordan (TYR-90), 8891 pk→Pakistan (TYR-95). Tremor uses `http://192.168.16.163:<port>` as per-source HTTP proxy.

Architecture/gotchas:
- **Container egress bypasses host wg0** via ip rule `from 172.30.0.0/16 lookup main pref 30000` (systemd unit `vpnproxy-egress-bypass.service`), so each gluetun builds its own per-country tunnel directly out ens19 instead of double-tunneling through the host's NL gateway. Decoupled from the client-gateway function.
- **`ManageForeignRoutingPolicyRules=no`** set in `/etc/systemd/networkd.conf.d/keep-foreign-rules.conf` — permanently stops netplan apply / networkd from flushing wg-quick AND the docker bypass rules (fixes the netplan-wipes-wg-rules gotcha above).
- **DoT (853) is blocked at some exits** (HK, Pakistan). Per-country `DOT_OFF` list in gen-compose.sh sets `DNS_UPSTREAM_RESOLVER_TYPE=plain` + `DNS_UPSTREAM_PLAIN_ADDRESSES=1.1.1.1:53` + `UPDATER_PERIOD=24h`. Currently cn,pk. Symptom of needing it: container unhealthy, `tun0` has traffic but healthcheck logs `lookup github.com: i/o timeout`.
- **HK/JP/TW/SG NordVPN datacenters do NOT complete a WG handshake from the Caiway home WAN** (tun0 RX stays 0 across every server + both direct and NL-tunnel egress paths; pubkeys/endpoints are correct). Myanmar & Pakistan (Asia) work fine. CEIC (ceic.ac.cn) is NOT China-geofenced — returns 200 through any non-EU exit — so cn just uses the Myanmar exit (borders China, reliably connects).
- **NordVPN simultaneous-connection limit = 10/account; we run 12** (11 proxies + host wg0). Works today because manual WG configs (same account key) aren't strictly torn down, but it's over quota and can cause intermittent handshake drops. If reliability matters, trim the fleet or move proxies to a second account.
- Diagnostic that lies: a standalone `wgtest` interface on the host using the same account key gives unreliable rx (skewed by the 12 concurrent sessions sharing the key). Trust the actual container `tun0` rx_bytes instead.
