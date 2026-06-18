# Bard agent — bootc image-mode node (read-only, small, immutable)

Runs the Bard agent on an **immutable RHEL 10 "bootable container"** (bootc
image-mode), so the node the **terminal tab** (#38) SSHs into is **read-only and
small** — only `/etc` and `/var` are writable. Modeled on
[`edhaynes/rhel10_imagemode`](https://github.com/edhaynes/rhel10_imagemode);
reuse its VM scripts (`create_qcow.sh` / `launch.sh` / `get_ipaddr.sh`) and
`ansible/` (`rhsm_register.yml`, `inject_creds.yml`, `bootc_update.yml`) — those
are generic to any bootc node.

## What's here
| File | Purpose |
|---|---|
| `Containerfile` | the bootc node image (`rhel10/rhel-bootc` + sshd + podman + the agent Quadlet) |
| `bard-agent.container` | the agent **Quadlet** — read-only, default-deny (#53), state on `/var/lib/bard` |
| `build.sh` | build + tag the bootc image (needs a **subscribed** build host) |
| `run-existing.sh` | **USE EXISTING** — pull a pre-built image + make a bootable qcow2 (no subscription) |

## Two paths

**A — Build it (needs a subscribed RHEL/fedora host).** `dnf update` inside the
`rhel-bootc` base pulls entitled content, so the build host must be
`subscription-manager register`ed.
```bash
printf '%s' '<operator-password>' > operator-password.txt   # gitignored
./build.sh && podman push "$BARD_BOOTC_IMAGE"
```

**B — Use existing (Mac/Windows + Podman Desktop, no subscription).** You can't
build without entitlement, but you can **pull a pre-built image and boot it**:
```bash
podman machine ssh --username core      # the fedora-core VM
./run-existing.sh                        # pull from Quay → qcow2 → boot (UTM/libvirt)
```
This is the path for a laptop without a subscribed builder: the image was built
once (path A, by whoever has entitlement) and published to Quay; everyone else
just consumes it.

## Why this is "read-only + small"
- **Read-only:** the OS is an immutable bootc image (`/usr` etc. read-only); the
  agent container also runs `ReadOnly=true` + `DropCapability=all` +
  `NoNewPrivileges` (#53). You can SSH in and look, but nothing mutates the node.
- **Small:** the node image is just `rhel-bootc` + sshd + podman + the Quadlet
  unit; the heavy runtime (Python + `llama-server`) is the **separate** agent
  image the Quadlet pulls, versioned and updated independently.
- **Immutable lifecycle:** update = build a new image version → `bootc update` →
  reboot into it (atomic), with `bootc rollback` to the prior image. (Use
  `rhel10_imagemode/ansible/bootc_update.yml`.)

## Secrets (never baked)
- `operator-password.txt` (the `bard` SSH user) — mounted as a build secret, gitignored.
- The fabric `BARDPRO_JWT_SECRET` + device-identity secrets — injected at **deploy**
  time (a `/var`-mounted env or a `Secret=`), never in the image.

## Prereqs (from rhel10_imagemode)
Red Hat account (free at developers.redhat.com), podman + ansible, a Quay repo
(`quay.io/ehaynes/...`), and a VM runner (UTM on Mac / libvirt on RHEL). Build
host must be subscribed; consumers (path B) need only podman.
