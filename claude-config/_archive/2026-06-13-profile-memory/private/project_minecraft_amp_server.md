---
name: Minecraft AMP server
description: minecraft-1a-nl2v.chosts.io runs CubeCoders AMP (Phobos 2.6.5.2); instances are dockerized; licence is pinned to the VM's machine id
type: project
originSessionId: 9e504fd1-bf42-4670-a83b-f7f10def567e
---
**Host:** `minecraft-1a-nl2v.chosts.io` (89.149.216.57, ssh port 2822, user `peter`)

**Stack:**
- Ubuntu 20.04.6, kernel 5.4.0-153-generic
- CubeCoders AMP Instance Manager v2.4.5.4 + AMP Phobos 2.6.5.2
- Docker 24.0.4 (cgroup v1, cgroupfs driver) — AMP runs each game instance in a `cubecoders/ampbase` container
- ADS (control panel) on :8080, SFTP on :2223, nginx on :80/:443
- 12 instances: 1 ADS + 10 Minecraft + 1 Generic (SanctumEmpireSQL)

**Admin shell:** `sudo su - amp`, then `ampinstmgr status|start|stop|reactivate <InstanceName>`

**Licence behaviour (important):** AMP Professional Edition licences are bound to a machine id derived from hardware fingerprint (DMI/SMBIOS UUID + /etc/machine-id). If the VM is migrated/cloned in a way that changes these, every instance fails at startup with `Licencing Error: NoMatchingMachineId` and must be reactivated with `ampinstmgr reactivate <InstanceName>` per instance.

**Why:** Proxmox 7→9 migration of this VM changed the hardware fingerprint, which invalidated all per-instance licences even though the ADS panel still runs.

**How to apply:** If instances won't start after any host-level change (migration, clone, restore-to-new-VMID), check `/home/amp/.ampdata/instances/<Name>/AMP_Logs/` for `NoMatchingMachineId` before debugging anywhere else.
