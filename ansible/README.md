# bard-infra / ansible — fleet management

Version-controlled Ansible config for the GPU/compute fleet. This replaces
hand-pasted console commands: the inventory, connection settings, and per-node
test/provision steps all live here as code.

## The fleet

| Host | OS | Role | Connection | State |
|------|-----|------|------------|-------|
| `gx10` (gladius) | Ubuntu aarch64 (Linux) | always-on compute node | SSH (`ehaynes`) | **works now** |
| `frogstation` | Windows 11 | GPU/ComfyUI helper, **daytime-only** | WinRM now → SSH later | needs vault creds |

Addresses are **Tailscale MagicDNS names** (`gx10`, `frogstation`). IPs churn; the
MagicDNS name is the stable handle and is what every `ansible_host` points at.

`frogstation` is powered off at night to keep noise down, so it being unreachable
overnight is normal, not a fault.

## Prerequisites (control node = this Mac)

The **Linux half needs nothing extra** — it runs over plain SSH.

The **Windows half** needs the Windows collections and a WinRM client library:

```bash
ansible-galaxy collection install ansible.windows community.windows
python3 -m pip install --user pywinrm   # MIT, pure-Python; installs the WinRM transport
```

`pywinrm` must be importable by the same Python that runs Ansible. On this Mac that
is the Homebrew Ansible interpreter; if `ansible all -m win_ping` complains it can't
find `winrm`, install `pywinrm` into that interpreter specifically.

## Filling the vault (frogstation credentials)

`frogstation`'s admin username and password are **not** in the repo. They live in an
ansible-vault encrypted file that Eddie creates:

```bash
cd ansible
# Put your vault password in a gitignored file the cfg points at:
echo 'YOUR-VAULT-PASSWORD' > .vault_pass    # gitignored

# Create the encrypted creds file (variable names shown in vault.yml.example):
ansible-vault create group_vars/windows_nodes/vault.yml
#   vault_frogstation_user: <the real admin username>
#   vault_frogstation_pass: <the real admin password>
```

`group_vars/windows_nodes/vault.yml` is gitignored. `vault.yml.example` (committed)
documents the two variable names with `CHANGEME` placeholders only.

## Running the connectivity test

```bash
cd ansible

# Linux only — works today, no vault required:
ansible-playbook playbooks/connectivity.yml --limit linux_nodes

# Whole fleet — once the vault creds exist:
ansible-playbook playbooks/connectivity.yml
```

The linux play does ping + `uname -srm` (expect aarch64). The windows play does
`win_ping` + `hostname`.

## The frogstation SSH plan

WinRM was just enabled on frogstation (HTTP :5985, firewall open to the tailnet
`100.64.0.0/10`). OpenSSH is **not** installed there — the Windows Update
Feature-on-Demand install hung.

The path to a consistent SSH-everywhere fleet:

1. **WinRM now** — use WinRM (this is what `group_vars/windows_nodes.yml` configures)
   to bootstrap the box once vault creds exist.
2. **Install OpenSSH** — run `playbooks/frogstation_install_openssh.yml`. It installs
   OpenSSH from the **Win32-OpenSSH GitHub release MSI** (not the WU feature), starts
   `sshd`, opens :22 to the tailnet, sets the default shell to PowerShell, and
   authorizes the Mac key into `administrators_authorized_keys` with the correct
   Administrators+SYSTEM-only ACLs.
3. **Consistent SSH fleet** — afterwards frogstation is reachable over SSH like gx10,
   and WinRM can be retired.

The OpenSSH version is pinned in `playbooks/frogstation_install_openssh.yml`
(`openssh_release_tag` / `openssh_msi_name`). See the comment there for how to bump it.

## Layout

```
ansible/
├── ansible.cfg
├── inventory/hosts.yml
├── group_vars/
│   ├── windows_nodes.yml                  # WinRM connection (refs vault vars)
│   └── windows_nodes/
│       ├── vault.yml.example              # committed: variable names + placeholders
│       └── vault.yml                       # gitignored, ansible-vault encrypted (Eddie)
├── playbooks/
│   ├── connectivity.yml                    # per-node connectivity test plan
│   └── frogstation_install_openssh.yml     # WinRM → install OpenSSH MSI → SSH
└── README.md
```
