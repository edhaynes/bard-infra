# Launch the Bard agent container on Windows (Podman Desktop / WSL2).
# Sibling of run_agent.sh.
#
#   $env:BARDPRO_JWT_SECRET = "..."; .\scripts\run_agent.ps1 [image]
param(
    [string]$Image = "bardllm-pro-agent:latest"
)
$ErrorActionPreference = "Stop"

$cpus      = if ($env:BARDPRO_CPUS)       { $env:BARDPRO_CPUS }       else { "2" }
$memory    = if ($env:BARDPRO_MEMORY)     { $env:BARDPRO_MEMORY }     else { "2g" }
$pidsLimit = if ($env:BARDPRO_PIDS_LIMIT) { $env:BARDPRO_PIDS_LIMIT } else { "256" }
$agentPort = if ($env:BARDPRO_AGENT_PORT) { $env:BARDPRO_AGENT_PORT } else { "8444" }
$sshPort   = if ($env:BARDPRO_SSH_PORT)   { $env:BARDPRO_SSH_PORT }   else { "2222" }

$args = @(
    "run", "--rm",
    "--cpus", $cpus,
    "--memory", $memory,
    "--pids-limit", $pidsLimit,
    "-e", "BARDPRO_JWT_SECRET",
    "-e", "BARDPRO_AGENT_ID",
    "-e", "BARDPRO_AGENT_PORT=$agentPort",
    "-p", "$($agentPort):$($agentPort)",
    "-p", "$($sshPort):22"
)
if ($env:BARDPRO_GPUS -eq "all") { $args += @("--gpus", "all") }
$args += $Image

podman @args
