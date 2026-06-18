# Fetch the GGUF model used by the llama.cpp inference backend (Windows).
# Sibling of fetch_model.sh.
#
# Everything is config-driven (CLAUDE.md §1); nothing is hardcoded beyond the
# documented defaults below, and every value is overridable by env var.
#
#   $env:BARDPRO_MODEL_URL     Source URL of the GGUF (default: small Qwen2.5-0.5B Q4).
#   $env:BARDPRO_MODEL_DIR     Target dir (default: ./models).
#   $env:BARDPRO_MODEL_SHA256  Optional: expected SHA-256; verified if set.
#
# Idempotent: a non-empty target file is left untouched. Fails loudly on any
# download or verification error (CLAUDE.md §10) — no silent fallback.
$ErrorActionPreference = "Stop"

# Small (~350 MB) instruct GGUF, Q4_K_M quant. Apache-2.0 license. Chosen as a
# laptop/CI-friendly default that runs without a GPU; override for production.
$DefaultModelUrl = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"

$ModelUrl = if ($env:BARDPRO_MODEL_URL) { $env:BARDPRO_MODEL_URL } else { $DefaultModelUrl }
$ModelDir = if ($env:BARDPRO_MODEL_DIR) { $env:BARDPRO_MODEL_DIR } else { "./models" }
$ModelPath = Join-Path $ModelDir "model.gguf"

# Idempotent: skip if already present and non-empty.
if ((Test-Path $ModelPath) -and ((Get-Item $ModelPath).Length -gt 0)) {
    Write-Host "fetch_model: $ModelPath already present; skipping download."
    exit 0
}

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null

Write-Host "fetch_model: downloading $ModelUrl"
Write-Host "fetch_model:   -> $ModelPath"

# Download to a temp file first so a partial download never leaves a truncated
# model.gguf that the idempotency check would later accept.
$TmpPath = "$ModelPath.partial"
try {
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $ModelUrl -OutFile $TmpPath -UseBasicParsing
}
catch {
    if (Test-Path $TmpPath) { Remove-Item -Force $TmpPath }
    Write-Error "fetch_model: ERROR — download failed from $ModelUrl : $_"
    exit 1
}

if (-not (Test-Path $TmpPath) -or ((Get-Item $TmpPath).Length -eq 0)) {
    if (Test-Path $TmpPath) { Remove-Item -Force $TmpPath }
    Write-Error "fetch_model: ERROR — downloaded file is empty: $ModelUrl"
    exit 1
}

# Optional checksum verification when BARDPRO_MODEL_SHA256 is set.
if ($env:BARDPRO_MODEL_SHA256) {
    $actual = (Get-FileHash -Path $TmpPath -Algorithm SHA256).Hash.ToLower()
    $expected = $env:BARDPRO_MODEL_SHA256.ToLower()
    if ($actual -ne $expected) {
        Remove-Item -Force $TmpPath
        Write-Error "fetch_model: ERROR — checksum mismatch (expected $expected, actual $actual)"
        exit 1
    }
    Write-Host "fetch_model: checksum OK"
}

Move-Item -Force $TmpPath $ModelPath
Write-Host "fetch_model: done -> $ModelPath"
