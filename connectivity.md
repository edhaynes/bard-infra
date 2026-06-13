# Connectivity — GPU hosts on the home network

Single source of truth for reaching Eddie's GPU workstations from a Mac.
Written after repeatedly losing time to the same handful of traps; read this
before debugging SSH again.

> Scope note: this is operational infra, not a universal coding rule. It
> lives here by explicit request so every machine/agent shares one
> authoritative copy. Secrets (private keys, passwords) MUST NOT be added —
> only host coordinates, OS usernames, and the **public** key.

## Physical hosts

**As of 2026-06-13 there are TWO GPU machines again.** The DGX Spark (gx10 /
gladius) is the primary GPU + ComfyUI host. The Windows GPU box (**frogstation**)
was **reimaged and recommissioned 2026-06-13** (Eddie) to help share GPU
workloads — this reverses the 2026-06-07 decommission. frogstation is currently
a **fresh Windows image**: back on the tailnet but **no services are up yet**
(no OpenSSH server, no ComfyUI) — bootstrap pending (see its section below). The
`brutus` compute persona is **not** revived; only frogstation (the
ComfyUI/upscale helper) returns.

| Box | Personas | LAN | Tailnet | OS | GPU |
|---|---|---|---|---|---|
| **Windows GPU** _(reimaged 2026-06-13)_ | frogstation (GPU/ComfyUI helper) | `10.0.0.36` (unverified post-reimage) | `100.92.74.65` (Tailscale-assigned; **may change** — reimaged box. Confirm: `tailscale status \| grep -i frog`) | Windows 11 (fresh) | RTX 5080, 16 GB |
| **DGX Spark** | gx10 (LAN) / gladius (Tailnet) — primary GPU + ComfyUI host | `10.0.0.97` | `100.97.246.73` (now lists under name `gx10`; re-auth if logged out) | Ubuntu 24.04 aarch64 | NVIDIA GB10, 121 GB unified |

The same `~/.ssh/id_ed25519` keypair is synced across the Macs (fingerprint
`SHA256:agtRlHEqB2mJKtg/P7Ujf0aljIdnk1QHWoJ9VC2DFEY`, comment
`edhayn@edwards-mbp`) — the key is rarely the problem; the **username** is.

### DNS — use Tailscale MagicDNS names, not IPs (no local DNS server needed)

**You do not need to stand up a local DNS server. Tailscale MagicDNS already
handles fleet name resolution** and is enabled on this tailnet (suffix
`taild08fd9.ts.net`). Every node is reachable by its **tailnet machine name**
from any other node — verified 2026-06-13: `frogstation` → `100.92.74.65`,
`gx10` → `100.97.246.73`, resolved by name on the Mac with no `/etc/hosts` or
DNS server involved.

**Prefer the MagicDNS name over a hard-coded IP** (`ssh gx10`, `ping
frogstation`). Tailscale-assigned `100.x` IPs can change — especially after a
reimage (frogstation's just did) — but the **name is stable**, so name-based
access survives IP churn. The hard-coded IPs in the tables below are a
fallback for when MagicDNS is unavailable (Tailscale down → use the LAN IP);
treat the names as authoritative.

> Note: this is distinct from the older "use the Tailscale IP, not the bare
> hostname" trap below — that warns against **LAN mDNS** (`frogstation.local`),
> which is flaky. **MagicDNS** (`frogstation`, resolving to the `100.x`
> address) is the reliable path and is what's meant here.

### Authorized public key (paste this into any new host)

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKQ7LAddzTIiH9TPeMMocvV2/cBmW5dF3lchn7xQVlt8 edhayn@edwards-mbp
```

## Username convention (target state: `ehaynes` everywhere)

We are standardizing on **`ehaynes`** as the SSH user across the fleet
because the per-host username drift (`edhay` / `edhayn` / `ehaynes`) has cost
multi-hour debugging sessions. Phase A (in progress 2026-05-24) is to add
`ehaynes` as a parallel admin account on every host that currently has a
different name. Phase B (deferred — see `features.md` F3) is to retire the
legacy accounts after their data has been migrated.

| Host | Current admin | Target admin |
|---|---|---|
| Windows GPU box | `edhay` (in use) | `ehaynes` (Phase A: parallel; Phase B: retire `edhay`) |
| DGX Spark | `ehaynes` ✓ | `ehaynes` ✓ |
| Macs | `edhayn` (this) / `ehaynes` (other) | `ehaynes` (Phase A: add parallel local user) |

**Until Phase A completes**, use the per-host username table below; do not
assume `ehaynes` works yet.

---

## The Windows OpenSSH admin-key trap

This is the single highest-cost gotcha on any Windows host where the SSH user
is in the local **Administrators** group. Windows OpenSSH **ignores**
`C:\Users\<user>\.ssh\authorized_keys` for admin accounts. The key MUST be in
`C:\ProgramData\ssh\administrators_authorized_keys` with ACLs restricted to
`Administrators` + `SYSTEM`.

A useful consequence: that file authorizes the key for **any** admin account
on the box. So adding a parallel admin user (e.g. `ehaynes` alongside `edhay`)
gets SSH access **automatically** — no key copy needed.

Authorizing a new machine's key (run in an **elevated** PowerShell on the
target Windows host):

```powershell
$k = '<paste the new machine ~/.ssh/id_ed25519.pub line>'
$f = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $f)) { New-Item -ItemType File -Force $f | Out-Null }
if ((Get-Content $f -Raw -EA SilentlyContinue) -notmatch [regex]::Escape($k)) { Add-Content $f $k }
icacls $f /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
Restart-Service sshd
```

Symptom of getting this wrong: `Permission denied (publickey,...)` from the
client, even though the key looks fine in `~/.ssh/authorized_keys`.

---

## Windows GPU box (frogstation)

> **RECOMMISSIONED 2026-06-13 (Eddie): frogstation was reimaged and is being
> brought back as a GPU/ComfyUI helper alongside gx10** — reversing the
> 2026-06-07 decommission. The `brutus` compute persona stays retired; only
> frogstation returns. **Current state: bare fresh Windows image.** On the
> tailnet at `100.92.74.65` (responds to ping; IP may change — it was just
> reimaged), but **SSH :22, ComfyUI :8188, and RDP :3389 are all refused** —
> none of those services are installed/enabled yet. Bootstrap required before
> it can help:
>   1. Enable the OpenSSH **server** on the fresh image and authorize the Mac
>      key via the admin-key trap (`administrators_authorized_keys`, below).
>      This needs Eddie at the console/RDP — the Mac can't SSH in to enable SSH.
>   2. Install Python + ComfyUI (+ torch CUDA for Blackwell) and the upscale
>      model so its ComfyUI can serve the image-upscale workflow.
>
> The model inventory and host facts below are **pre-reimage history** — the
> fresh image has none of it; re-verify after bootstrap. The SSH-config block,
> account convention, and traps below still apply to the new OpenSSH install.

The hostname was `FrogStation`. Accounts (historical):

- **`edhay`** — legacy account, owner of ComfyUI installation and most data.
  Accessed via the `frogstation` SSH alias.
- ~~**`ehaynes`** — parallel admin for the `brutus` persona / automation
  work, via the `brutus` SSH alias.~~ _Retired with Brutus (2026-06-07)._

### Working `~/.ssh/config` blocks

```
Host frogstation
    HostName 100.82.167.91        # Tailscale IP (stable; mDNS name is flaky)
    User edhay
    IdentityFile ~/.ssh/frogstation_ed25519
    IdentitiesOnly yes

Host brutus
    HostName 100.82.167.91        # Same physical box as frogstation
    User ehaynes
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Verify: `ssh frogstation 'powershell -NoProfile -Command "whoami; hostname"'`
→ `frogstation\edhay` / `FrogStation`. (`ssh brutus` requires Phase A
complete.)

### The traps (in order of how much time they've cost)

1. **Wrong username.** SSH defaults `User` to the *local* Mac account
   (`edhayn` on edwards-mbp, `ehaynes` on ehaynes-mac). Wrong user →
   `Permission denied (publickey,...)` even with a trusted key. Always pin
   the `User` directive per host until the Phase B consolidation lands.
2. **Admin-key trap** (see global section above).
3. **Use the Tailscale IP, not the bare hostname.** `frogstation` may be in
   `known_hosts` and resolve via mDNS/LAN to an address where auth differs
   or the host is unreachable. `100.82.167.91` is the Tailnet address and is
   the reliable target. (`tailscale status | grep frog` to confirm/refresh.)
4. **LAN-vs-Tailnet IP collision.** The same box answers on **LAN `10.0.0.36`**
   (Windows OpenSSH is bound to all interfaces). `ssh edhay@10.0.0.36`
   returns `frogstation\edhay` and is functionally identical to going via
   Tailnet — useful when Tailscale routing is down.
5. **Windows blocks ICMP by default.** `ping frogstation` will fail even when
   the host is fully reachable. Confirm liveness with TCP probes instead:
   `nc -zv 10.0.0.36 22` (port 22 should succeed; banner reports
   `SSH-2.0-OpenSSH_for_Windows_9.x`).

### Host facts (verified 2026-05-24)

| Item | Value |
|---|---|
| Tailnet IP | `100.82.167.91` (Tailscale, owner `ed.haynes.h@`) |
| LAN IP | `10.0.0.36` |
| OS users | `edhay` (admin, in use); `ehaynes` (admin, Phase A target) |
| Host | Windows 11, hostname `FrogStation` |
| GPU | NVIDIA GeForce RTX 5080, ~16 GB VRAM (Blackwell) |
| RAM | ~32 GB |
| CPU | AMD Ryzen 7 7700 (8C/16T, Zen 4) |
| SSH | OpenSSH for Windows 9.5 |
| ComfyUI | v0.21.1, launched `main.py --listen 0.0.0.0 --port 8188` (under `edhay`) |
| Reachable | `http://100.82.167.91:8188` (bound to all interfaces) |
| Python | 3.12.10 (system, not embedded) |
| PyTorch | 2.11.0+cu128 (CUDA 12.8 — Blackwell-capable) |

### ComfyUI model inventory (verified 2026-05-17, via `/object_info`)

| Slot | Available |
|---|---|
| Checkpoints | `flux1-schnell-fp8.safetensors` (FLUX, all-in-one) |
| UNET / diffusion | `flux1-dev-kontext_fp8_scaled.safetensors` (FLUX.1 Kontext dev) |
| CLIP | (none — no separate `DualCLIPLoader` files) |
| VAE | `ae.safetensors` (FLUX VAE), `pixel_space` |
| LoRAs | (none installed) |

**Implication:** this box is a **FLUX** ComfyUI box — no SDXL checkpoint
and no LoRAs. Tools assuming SDXL + Kohya LoRA (e.g. `charconsist`) need
either an SDXL checkpoint added or a FLUX-shaped pivot before they can run
here.

### Quick probes

```bash
# health / GPU / torch
ssh frogstation 'powershell -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats).Content"'

# what models ComfyUI can see
ssh frogstation 'powershell -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/object_info/CheckpointLoaderSimple).Content"'
```

### Trap 6 — stale ComfyUI squatting :8188

**Symptom:** every job fails with `KSampler … OSError: [Errno 22] Invalid
argument`, while `/system_stats` and `/object_info` still answer fine. A
"fresh" relaunch doesn't help and the error message keeps the *same* cached
nodes.

**Cause:** an old ComfyUI process (often the **system** Python
`C:\Users\edhay\AppData\Local\Programs\Python\Python312\python.exe`, not the
`.venv` one) still owns port 8188. New launches via
`.venv\Scripts\python.exe` silently fail to bind, so the broken detached
instance keeps serving — its sampler writes to a dead console handle →
`[Errno 22]`. Verified-fresh process shows much higher free VRAM
(~14.6 GiB vs ~8 GiB on the wedged one) and an empty execution cache.

**Fix (run on frogstation, elevated PowerShell):**

```powershell
# identify what owns 8188 (confirm it's python before killing)
Get-NetTCPConnection -LocalPort 8188 -State Listen | ForEach-Object { Get-Process -Id $_.OwningProcess | Select-Object Id,ProcessName,Path }
# kill it
Get-NetTCPConnection -LocalPort 8188 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
# confirm free (prints nothing)
Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue
```

Then relaunch from the **`.venv`** in a console you keep open:

```cmd
set TQDM_DISABLE=1
cd C:\Users\edhay\ComfyUI
.venv\Scripts\python.exe main.py --listen 0.0.0.0 --port 8188
```

Always launch ComfyUI from its own `.venv`, not system Python, and from a
real local console (not an SSH pipe / detached) — both independently cause
the `[Errno 22]` class of failure.

---

## DGX Spark (gx10 / gladius)

NVIDIA GB10 Grace-Blackwell, 121 GB unified memory, aarch64 Ubuntu 24.04.
**Gladius MUST stay joined to the tailnet** so it is reachable off-LAN.
`tailscaled` runs as a system service (`active` + `enabled`). If a Mac's
`tailscale status` does not list `gladius`, the node has been **logged out** —
re-authenticate on the host and complete the browser login as `ed.haynes.h@`:

```bash
ssh -t gx10 'sudo tailscale up'   # prints an auth URL; open it, approve gladius
```

(Logged-out incident 2026-06-06: daemon was up but `BackendState: NeedsLogin`;
fixed by re-running `tailscale up`. Until login completes, access is LAN-only
via `10.0.0.97`.)

### Working `~/.ssh/config` block

```
Host gx10
    HostName 10.0.0.97
    User ehaynes
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Verify: `ssh gx10 'uname -srm; whoami'` → `Linux 6.17.0-... aarch64` / `ehaynes`.

### Traps

1. **User is `ehaynes`** here (Linux), not `edhay` or `edhayn`. This is the
   only host that already matches the target convention.
2. **Disk layout matters.** Root partition `/dev/nvme0n1p2` is only 100 GB
   (often <30 GB free). The big partition is `/dev/nvme0n1p3` mounted at
   `/srv/models` (831 GB). Put HF caches, model checkpoints, and training
   outputs there:
   ```bash
   export HF_HOME=/srv/models/huggingface
   ```
3. **aarch64 != x86_64.** Some packages ship x86-only wheels. PyTorch ARM CUDA
   wheels exist; `bitsandbytes` aarch64 works but is less battle-tested.
4. **nvidia-smi memory readings are `[N/A]` on Grace-Blackwell** because the
   GPU shares unified memory with the CPU. Use `torch.cuda.memory_allocated()`
   or `nvidia-smi pmon -c 1` for per-process compute stats instead.
5. **Low GPU power draw isn't a problem.** GB10 in 4-bit small-model
   workloads typically runs at 10–20 W (vs. 240 W on a discrete H100). The
   `utilization.gpu` field can read 95 % while real compute is light — use
   step time and loss curve as the real signal.

### Host facts (verified 2026-05-24)

| Item | Value |
|---|---|
| LAN IP | `10.0.0.97` |
| Tailnet name | `gladius` (daemon active+enabled; `sudo tailscale up` to re-auth if logged out) |
| OS user | `ehaynes` |
| Host | Ubuntu 24.04 LTS, kernel 6.17, aarch64 |
| GPU | NVIDIA GB10 (Grace-Blackwell), shares unified 121 GB |
| CUDA | 13.0, driver 580.x |
| Disks | `/dev/nvme0n1p2` 100 GB → `/` ; `/dev/nvme0n1p3` 831 GB → `/srv/models` |
| Tooling | `uv` at `~/.local/bin/uv` |

---

## Triage — host appears unreachable

Same recipe across all hosts. Work from cheap probes up.

1. **DNS resolution**: `ssh -G <host> | grep ^hostname`. If it resolves to a
   stale IP or fails entirely, the alias or Tailnet routing is off.
2. **TCP reachability**: `nc -zv -G 3 <ip> 22`. Windows hosts won't reply to
   `ping` but will accept SSH connections — don't conclude "dead" from a
   ping timeout.
3. **SSH banner**: `echo "" | nc -G 3 -w 3 <ip> 22 | head -1`. If you see
   `SSH-2.0-OpenSSH_for_Windows_...` you know the host is a Windows OpenSSH
   server; if `SSH-2.0-OpenSSH_for_Linux_...` it's a Linux daemon. Useful for
   confirming you're talking to the host you think you are.
4. **Identity check** (best for confirming you've reached the right *box*,
   not just the right port): `ssh <known-user>@<ip> 'cmd /c hostname'` on
   Windows or `ssh <known-user>@<ip> hostname` on Linux. Returns the OS
   hostname — if `FrogStation`, you're on the Windows GPU box (regardless of
   which persona alias you used).
5. **Tailscale**: `/Applications/Tailscale.app/Contents/MacOS/Tailscale status`
   on the Mac. Hosts missing from the list aren't on the tailnet right now —
   probably powered off or their client is logged out. Fix at the host
   directly (open the Tailscale tray icon / log in).
6. **Auth**: `ssh -vv <host> 2>&1 | grep -E "Authenticating|preferred|Authentications"`
   shows which keys are being offered and what the server is willing to
   accept. `Permission denied (publickey)` despite a trusted-looking key is
   almost always the admin-key trap (Windows) or a wrong `User` directive.

See also `rules/network-security.md` for the Tailscale zero-trust mesh
requirements these hosts operate under.
