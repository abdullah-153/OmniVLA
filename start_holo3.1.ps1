<#
.SYNOPSIS
    Starts the 6 GB-friendly Holo-3.1-4B local VLM backend.
.PARAMETER ModelPath
    Path to the primary LLM GGUF model.
.PARAMETER MmprojPath
    Path to the multimodal vision projector model.
.PARAMETER GpuLayers
    Number of layers to offload to the GPU (-1 offloads all).
.PARAMETER ContextSize
    Context window size (defaults to 4096).
.PARAMETER Port
    Port number for the API server (defaults to 8080).
.PARAMETER ParallelSlots
    Number of concurrent llama-server slots. One is the safe default for a
    single interactive desktop agent on a 6 GB GPU.
.PARAMETER HostIP
    Binding host IP address (defaults to 127.0.0.1).
.PARAMETER LogDir
    Directory where logs and PID files will be stored.
.PARAMETER Detached
    If set, the script starts the process, verifies health, and exits immediately.
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$ModelPath = "$PSScriptRoot\models\Holo-3.1-4B-abliterated-rdo.Q4_K_M.gguf",

    [Parameter(Mandatory = $false)]
    [string]$MmprojPath = "$PSScriptRoot\models\Holo-3.1-4B.mmproj-f16.gguf",

    [Parameter(Mandatory = $false)]
    [int]$GpuLayers = -1,

    [Parameter(Mandatory = $false)]
    [int]$ContextSize = 4096,

    [Parameter(Mandatory = $false)]
    [int]$Port = 8080,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 4)]
    [int]$ParallelSlots = 1,

    [Parameter(Mandatory = $false)]
    [string]$HostIP = "127.0.0.1",

    [Parameter(Mandatory = $false)]
    [string]$LogDir = "$PSScriptRoot\logs",

    [Parameter(Mandatory = $false)]
    [switch]$Detached
)

# --- Initialize Paths & Directories ---
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$OutLog = Join-Path $LogDir "llama_server.out.log"
$ErrLog = Join-Path $LogDir "llama_server.err.log"
$PidFile = Join-Path $LogDir "llama_server.pid"
$ExePath = Join-Path $PSScriptRoot "llama-cpp\llama-server.exe"

Write-Host "========================================="
Write-Host " Holo-3.1-4B Server Starter Tool"
Write-Host "========================================="

# --- 1. Pre-Flight Checks ---

# 1.1 Executable Check
if (-not (Test-Path $ExePath)) {
    Write-Error "llama-server.exe executable not found at: $ExePath"
    exit 1
}

# 1.2 Model File Checks
if (-not (Test-Path $ModelPath)) {
    Write-Error "Model file not found at: $ModelPath"
    exit 1
}
if (-not (Test-Path $MmprojPath)) {
    Write-Error "Vision projector mmproj file not found at: $MmprojPath"
    exit 1
}

# 1.3 Duplicate Instance Check via PID File
if (Test-Path $PidFile) {
    $ExistingPid = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
    if ($ExistingPid -and ($ExistingPid.Trim() -match '^\d+$')) {
        $ActiveProc = Get-Process -Id ([int]$ExistingPid.Trim()) -ErrorAction SilentlyContinue
        if ($ActiveProc -and $ActiveProc.ProcessName -eq "llama-server") {
            Write-Error "llama-server is already running with PID: $ExistingPid. Run stop script first."
            exit 1
        }
    }
}

# 1.4 Port Conflict Check
$PortOccupied = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($PortOccupied) {
    $ConflictingPid = $PortOccupied.OwningProcess[0]
    Write-Error "Port $Port is already in use by PID: $ConflictingPid. Select another port."
    exit 1
}

# 1.5 GPU Hardware Warning
$NvidiaGpu = Get-CimInstance -ClassName Win32_VideoController | Where-Object { $_.Name -like "*NVIDIA*" }
if (-not $NvidiaGpu) {
    Write-Warning "NVIDIA GPU not detected. Offloading layers to GPU is not possible. Running in CPU fallback mode."
} else {
    Write-Host "NVIDIA Hardware Found: $($NvidiaGpu.Name) [Driver: $($NvidiaGpu.DriverVersion)]" -ForegroundColor Green
}

# --- 2. Arguments Assembly ---
$Arguments = @(
    "-m", $ModelPath,
    "--mmproj", $MmprojPath,
    "-ngl", $GpuLayers,
    "-ctk", "q8_0",
    "-ctv", "q8_0",
    "-fa", "on",
    "-c", $ContextSize,
    "-np", $ParallelSlots,
    "--cache-prompt",
    "--batch-size", "512",
    "--threads", "8",
    "--threads-batch", "8",
    "--port", $Port,
    "--host", $HostIP
)

# --- 3. Process Launch ---
Write-Host "Launching llama-server process..." -ForegroundColor Cyan
$Proc = Start-Process -FilePath $ExePath -ArgumentList $Arguments `
                      -NoNewWindow `
                      -RedirectStandardOutput $OutLog `
                      -RedirectStandardError $ErrLog `
                      -PassThru

if (-not $Proc -or $Proc.HasExited) {
    Write-Error "llama-server failed to launch. Verify stderr logs in: $ErrLog"
    exit 1
}

$ServerPid = $Proc.Id
$ServerPid | Out-File -FilePath $PidFile -Encoding ascii -Force
Write-Host "Process spawned with PID: $ServerPid (PID file written to: $PidFile)" -ForegroundColor Green

# --- 4. Health Check loop ---
Write-Host "Waiting for model to load and API to initialize..." -NoNewline
$IsHealthy = $false
$TimeoutSec = 60
$PollIntervalSec = 2
$MaxRetries = $TimeoutSec / $PollIntervalSec

for ($i = 1; $i -le $MaxRetries; $i++) {
    if ($Proc.HasExited) {
        Write-Error "`nProcess terminated unexpectedly with ExitCode: $($Proc.ExitCode). Check $ErrLog."
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
        exit 1
    }

    try {
        # Perform HTTP GET request to /health endpoint
        $Health = Invoke-RestMethod -Uri "http://$HostIP`:$Port/health" -Method Get -TimeoutSec 2
        # llama-server health response contains a status code check
        $IsHealthy = $true
        break
    }
    catch {
        # Server API not listening yet or model weight allocation in progress
        Write-Host "." -NoNewline
        Start-Sleep -Seconds $PollIntervalSec
    }
}

if (-not $IsHealthy) {
    Write-Error "`nServer failed to become healthy within $TimeoutSec seconds. Terminating process."
    $Proc.Kill()
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    exit 1
}

Write-Host "`nServer is online and healthy!" -ForegroundColor Green

# --- 5. Mode Execution Execution Block ---
if ($Detached) {
    Write-Host "Detached flag detected. Relinquishing process control and exiting." -ForegroundColor Yellow
    exit 0
}

# Monitor Mode (Foreground Loop)
try {
    Write-Host "Running in MONITOR mode. Keeping process active in console." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to terminate the server gracefully." -ForegroundColor Yellow
    while ($true) {
        if ($Proc.HasExited) {
            Write-Warning "llama-server process exited independently."
            break
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    Write-Host "Shutdown hook triggered. Shutting down llama-server..." -ForegroundColor Yellow
    if (-not $Proc.HasExited) {
        $Proc.Kill()
        # Wait up to 3 seconds for release of VRAM and file descriptors
        $Proc.WaitForExit(3000)
    }
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force
    }
    Write-Host "Clean exit completed." -ForegroundColor Green
}
