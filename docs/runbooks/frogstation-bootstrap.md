# Runbook — bootstrap frogstation (fresh Windows image)

**Goal.** Take frogstation from a bare fresh Windows 11 image (reimaged
2026-06-13) to a reachable GPU/ComfyUI helper on the tailnet, sharing image
workloads alongside gx10.

**Why a runbook.** `connectivity.md` records the post-reimage state: on the
tailnet (`100.92.74.65`, may change) and answers ping, but **SSH :22,
ComfyUI :8188, and RDP :3389 are all refused** — none of those services are
installed yet. The Mac cannot SSH in to enable SSH, so the first steps need
Eddie **at the console or over RDP**.

**Legend.** `[CONSOLE]` = run at the Windows box (physical console or RDP);
`[MAC]` = run from the Mac. Each step has a **Verify** with a clear done-signal.
Do them in order; do not skip a Verify.

---

## Step 0 — [MAC] Confirm the box is on the tailnet and get its current IP

The reimaged box's Tailscale IP can change. Get the name→IP truth before anything.

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale status | grep -i frog
```

**Verify:** a line for `frogstation` with a `100.x` address. Prefer the **name**
`frogstation` from here on (MagicDNS is stable; the IP is not). If absent, the
box is off the tailnet — fix at the Windows Tailscale tray icon first.

---

## Step 1 — [CONSOLE] Create/confirm the admin account

Username convention target is `ehaynes` (see `connectivity.md`). On the fresh
image, confirm which admin account exists and note it for the SSH `User`
directive later.

```powershell
whoami
hostname
net localgroup Administrators
```

**Verify:** prints the logged-in admin user and `FrogStation` (or the new
hostname). Record the exact username — Windows SSH defaults to the *Mac* local
username otherwise, the #1 time-sink trap.

---

## Step 2 — [CONSOLE] Install + enable the OpenSSH server

The Mac cannot do this remotely — SSH is the thing being enabled.

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Get-NetFirewallRule -Name *ssh* | Select-Object Name,Enabled,Direction,Action
```

**Verify:** `Get-Service sshd` reports `Running`; a firewall rule allows inbound
TCP 22. From the Mac: `nc -zv frogstation 22` succeeds and the banner reads
`SSH-2.0-OpenSSH_for_Windows_9.x` (`echo "" | nc -G 3 -w 3 frogstation 22 | head -1`).
Note: Windows blocks ICMP, so `ping` failing is **not** a failure here.

---

## Step 3 — [CONSOLE] Authorize the Mac key (admin-key trap)

The single highest-cost gotcha: Windows OpenSSH **ignores**
`C:\Users\<user>\.ssh\authorized_keys` for accounts in the Administrators
group. The key MUST go in `administrators_authorized_keys` with restricted ACLs.
This authorizes the key for **any** admin account on the box (so a later
parallel `ehaynes` admin gets in automatically).

```powershell
$k = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKQ7LAddzTIiH9TPeMMocvV2/cBmW5dF3lchn7xQVlt8 edhayn@edwards-mbp'
$f = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $f)) { New-Item -ItemType File -Force $f | Out-Null }
if ((Get-Content $f -Raw -EA SilentlyContinue) -notmatch [regex]::Escape($k)) { Add-Content $f $k }
icacls $f /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
Restart-Service sshd
```

> The key above is the Mac's **public** key, already published in
> `connectivity.md` — public keys only, never a private key (rubric dim 3).

**Verify:** `icacls $f` shows only `Administrators` and `SYSTEM`. Real test is
Step 4.

---

## Step 4 — [MAC] Prove SSH works end-to-end

Pin the `User` (do not rely on the Mac's local username). Replace `<user>` with
the account confirmed in Step 1.

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 <user>@frogstation \
    'powershell -NoProfile -Command "whoami; hostname"'
```

**Verify:** returns `frogstation\<user>` and the hostname. `Permission denied
(publickey,...)` here is almost always the wrong `User` (Step 1) or the
admin-key ACLs (Step 3). Once green, add a `Host frogstation` block to
`~/.ssh/config` with `User <user>` and `IdentityFile ~/.ssh/id_ed25519`.

---

## Step 5 — [MAC→box] Install Python + CUDA PyTorch (Blackwell)

frogstation is an RTX 5080 (Blackwell) — needs a CUDA 12.8+ PyTorch build.
Install Python 3.12 first (winget at the console if absent), then a venv'd
PyTorch. Run over SSH or at the console.

```powershell
python --version
python -m venv C:\Users\<user>\ComfyUI\.venv
C:\Users\<user>\ComfyUI\.venv\Scripts\python.exe -m pip install --upgrade pip
C:\Users\<user>\ComfyUI\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128
```

**Verify:**

```powershell
C:\Users\<user>\ComfyUI\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

prints a `+cu128` torch, `True`, and `NVIDIA GeForce RTX 5080`.

---

## Step 6 — [box] Install ComfyUI + the upscale model

```powershell
cd C:\Users\<user>
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Place the upscale model under `ComfyUI\models\upscale_models\`.

**Verify:** the model file is present and non-zero
(`Get-Item ComfyUI\models\upscale_models\*`).

---

## Step 7 — [CONSOLE] Launch ComfyUI from its own venv

Always launch from `.venv` in a **real local console** you keep open — not a
detached SSH pipe. Both system-Python and SSH-pipe launches independently cause
the `[Errno 22]` KSampler failure class (see `connectivity.md` Trap 6).

```cmd
set TQDM_DISABLE=1
cd C:\Users\<user>\ComfyUI
.venv\Scripts\python.exe main.py --listen 0.0.0.0 --port 8188
```

**Verify:** from the Mac,

```bash
ssh <user>@frogstation \
    'powershell -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8188/system_stats).Content"'
```

returns JSON with the GPU listed and healthy free VRAM (~14+ GiB on a fresh
process). `nc -zv frogstation 8188` from the Mac also succeeds.

---

## Step 8 — [MAC] Record verified facts back into connectivity.md

The pre-reimage host-facts and model-inventory tables in `connectivity.md` are
**history** — re-verify and update them with the new IP, confirmed username,
torch/ComfyUI versions, and the installed upscale model. Flip the host's status
line from "bootstrap pending" to verified-up with today's date.

**Done-signal (whole runbook):** `ssh frogstation` returns the host identity,
`http://frogstation:8188/system_stats` is healthy from the Mac, and
`connectivity.md` reflects the post-bootstrap reality.
