# Source this before running WinRM (Windows/frogstation) plays from a Mac.
#   source ./winrm-env.sh && ansible-playbook playbooks/connectivity.yml
#
# Why: on macOS, Ansible forks a worker per task; the WinRM path (pywinrm ->
# requests -> macOS proxy auto-detection, which is Objective-C) aborts in the
# forked child ("crashed on child side of fork pre-exec" / "A worker was found in
# a dead state"). These two env vars disable the fork-safety abort and the proxy
# lookup that triggers it. The SSH/Linux path never forks into this, so it's
# WinRM-only. (Established 2026-06-16.)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy='*'
