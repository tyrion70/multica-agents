---
name: homeassistant
description: Operate Peter's Home Assistant (homeassistant.252h.org) — read/control entities, write & debug automations, the energy dashboard, climate/solar/battery, sensors. Use whenever a task touches this HA via its REST API, websocket API, or SSH into the box. Auth token lives in the vault (see the `bitwarden` skill); SSH uses `id_ed25519_peter` (see the `ssh` skill).
---

# Home Assistant — homeassistant.252h.org

Peter's home HA. Personal/homelab infra (not ChainLayer). Snapshots below are
point-in-time — **verify entity/file names against the live system before acting.**

## Permission model

- ✅ **Safe / do freely:** read state (`GET /api/states`), render templates, list
  registries, read logs, `check_config`, dry-run computations, read the ESS export.
- 🔶 **Confirm intent first:** call services that actuate hardware (turn the airco
  on/off, set temp), create/edit automations, rename/hide entities, assign areas,
  edit `alerts.yaml`, reload template/automation, re-add an integration.
- 🛑 **Explicit go-ahead + dry-run, every time:** anything that mutates recorder
  history (`recorder/import_statistics`, `adjust_sum_statistics`, `clear_statistics`),
  a full HA **restart**, editing `custom_components/*`, deleting entities/devices.
  The auto-mode classifier blocks these without clear consent — that's correct.

## Authentication (token in Bitwarden)

The Long-Lived Access Token is in the vault — **item `Home Assistant — 252h.org (API + SSH)`,
`private` folder**, hidden field `HA_TOKEN` (also `HA_URL`, `HA_SSH_HOST`, `HA_SSH_USER`,
`HA_SSH_KEY`). Fetch it via the **`bitwarden` skill** (unlock with the bootstrap env, then
parse the SecureNote). Convenience wrapper (assumes vault already unlocked / `BW_SESSION` set):

```bash
TOKEN="$($HOME/.claude/skills/homeassistant/scripts/ha-token.sh)"
```

The wrapper does **not** unlock — do that per the `bitwarden` skill first
(`export BW_SESSION=$(… bw unlock --raw --passwordenv BW_PASSWORD)`). Never print the token.
A legacy plaintext copy at `~/.ha_token` may still exist; prefer the vault, and that file
can be deleted once vault retrieval is confirmed.

## How to talk to HA

- **URL** `https://homeassistant.252h.org/` · ~2026.2.x · Europe/Amsterdam · °C · ~1950 entities.
- **Stack:** Zigbee2MQTT (hex `0x…` ids), UniFi Protect, 2× Carlo Gavazzi EM24 modbus, Victron (sfstar HACS).

**REST** — `Authorization: Bearer $TOKEN` @ `https://homeassistant.252h.org/api/`:
`GET /api/states[/<id>]` · `POST /api/services/<domain>/<service>` ·
`POST /api/config/automation/config/<id>` (UI automation) ·
`POST /api/config/core/check_config` (before reloads/restart) ·
`POST /api/services/{template,automation}/reload` · `POST /api/template` ·
config flows are HTTP: `POST /api/config/config_entries/flow` then `…/flow/<flow_id>`.

**Websocket** (registry, energy, dashboards, statistics — NOT in REST) — `wss://…/api/websocket`,
auth `{"type":"auth","access_token":TOKEN}`. Use a venv with `websockets`
(`python3 -m venv /tmp/ha_venv && /tmp/ha_venv/bin/pip install websockets`; system python is PEP-668).
Commands: `config/{area,device,entity}_registry/list|update|remove` (rename via `name`, hide via
`hidden_by:"user"`), `energy/{get,save}_prefs`, `lovelace/dashboards/*` + `lovelace/config*`,
`recorder/statistics_during_period|import_statistics|adjust_sum_statistics|clear_statistics`,
`config_entries/get`, `system_log/list`, `get_states`, `hacs/repositories/list`, `hacs/repository/remove`.

**SSH** (YAML + custom components) — `ssh -i ~/.ssh/id_ed25519_peter hassio@192.168.17.194`
(key per the `ssh` skill; host/user in the BW item). Login user `hassio` is **read-only on `/config`
— use `sudo`** for writes. The `ha` CLI lacks the supervisor token over SSH → use REST `check_config`.
Config: `configuration.yaml` → `automations.yaml` + `homeassistant: packages: !include_dir_named
config/packages` → `/config/config/packages/*.yaml`; inline `modbus:` block (~line 85) = the 2 EM24s.
**Custom-component code changes need a full HA restart** (config-entry reload reuses the imported module);
clear the component's `__pycache__`.

## Key entities & automations

- **Shed airco** `climate.shed_air_conditioner` — automation `shed_ac_auto_cool`: ON room >26 / OFF
  room <24, cool target 18. **Triggers on `sensor.up_sense_schuur_temperature` (room), NOT the airco's
  onboard temp** (onboard reads ~3-4°C low and drops far below the room while cooling → shut off early).
  **Level-based + self-healing** (since 2026-06-12): besides the >26/<24 numeric_state crossings it also
  re-evaluates on `homeassistant` start and every 10 min (`time_pattern`), actions gated on current room
  temp + airco state — so an HA restart while already >26 no longer strands it off (a pure numeric_state
  edge is lost across restarts; this bit us once after a restart landed mid-crossing).
- **Safety alerts** in `/config/config/packages/alerts.yaml` — template binary_sensors
  `any_{smoke_detected,smoke_tamper,leak_detected,low_battery,safety_device_offline}` + `Alert –`/`Notify –`
  automations → `notify.mobile_app_iphone_17_peter` (+ `…iphone_von_bibi`, `…ipad_pro_van_peter_5th`).
  Offline alert watches smoke+leak only and fires on NEW offenders.
- 21 areas defined; ACs assigned. "Home Overview" dashboard at `/claude-overview`.

## Energy dashboard (websocket `energy/*`)

- **Grid** P1 dual-tariff `sensor.energy_{consumed,produced}_tariff_1/2`; gas + water set.
- **Solar — two arrays:** SolarEdge = `sensor.solar_reference_network` (EM24 SOLAR meter total;
  Victron's `pvinverter_*` is the SAME SolarEdge via the EM24 — do **not** add it / double-count).
  Victron MPPT = `sensor.victron_solarcharger_yield_user` (Oost Rood) / `_1` (West Paars) / `_2` (Zuid Groen).
- **Battery** in=`sensor.victron_battery_power_charge_sum`, out=`…discharge_sum`.

## Gotchas / lessons

- **Victron (sfstar/hass-victron) has TWO LOCAL PATCHES.** Both are overwritten by a HACS update →
  re-apply together (Peter does not auto-update this integration). Backups on the box: `…/victron/*.bak-claude*`.
  1. `const.py` (~line 728) — `vebus_microgrid_error` passed `TextReadEntityType` positionally as `unit`
     → non-serializable `unit_of_measurement` that **500s all of `/api/states`**. Fix: add `entityType=`. (upstream #444/#439)
  2. `sensor.py` (`_handle_coordinator_update`, ~line 188) — text/enum registers returning `65535`
     (0xFFFF = "not available") hit the `else` and **error-logged every poll** (67,980× in days). Fix:
     `elif data == 65535: self._attr_native_value = None` before the `else`. (upstream #433)
- **Statistics backfill:** per-string MPPT gap totals come from the hardware counter jump
  (reconnect_state − freeze_state), exact; ESS export gives only the hourly *shape*. Import
  (`source:"recorder"`, has_sum, kWh) then `adjust_sum_statistics +gap_total` at reconnect to keep sums
  continuous. **Don't re-derive gap totals at runtime via "last hour with change>0" — once live it picks
  a current hour → 0.**
- **ESS export** `http://dev.252h.org:3000/api/export/timeseries` (GET bare = howto). `solar` dataset is
  COMBINED only; per-array `solar_power` is empty for historical gaps.
- **numeric_state automations** fire only on the crossing edge — already-past-threshold on reload won't fire.

## Outstanding (physical / Peter)

Offline smoke detectors (Gym, Hallway Upstairs, Bedroom Nova) + low batteries + offline Aqara leak sensors;
shed whole-feed meter (EM24 fits the modbus config, or Shelly Pro 3EM); ~50 unnamed Z2M lights/switches
(rename in Z2M UI); considering migrating flaky Aqara (battery+Zigbee) → UniFi (UP Sense / new UniFi smoke).
