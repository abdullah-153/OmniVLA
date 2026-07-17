<#
.SYNOPSIS
    Stops the llama-server process associated with the Holo-3.1-9B VLM server.
.PARAMETER LogDir
    Directory containing logs and the active PID file (defaults to $PSScriptRoot/logs).
#>
[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$LogDir = "$PSScriptRoot\logs"
)

$PidFile = Join-Path $LogDir "llama_server.pid"
$TargetProcess = $null

Write-Host "========================================="
Write-Host " Holo-3.1-9B Server Stopper Tool"
Write-Host "========================================="

# 1. Resolve Process from PID File
if (Test-Path $PidFile) {
    $SavedPid = Get-Content $PidFile -Raw -ErrorAction SilentlyContinue
    if ($SavedPid -and ($SavedPid.Trim() -match '^\d+$')) {
        $SavedPidInt = [int]$SavedPid.Trim()
        Write-Host "Found PID file with recorded process ID: $SavedPidInt"
        $TargetProcess = Get-Process -Id $SavedPidInt -ErrorAction SilentlyContinue
    }
}

# 2. Fallback to Process Name lookup if PID file doesn't resolve active process
if (-not $TargetProcess) {
    Write-Warning "Process not found by PID file. Scanning for processes named 'llama-server'..."
    $TargetProcess = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
}

# 3. Terminate Process
if ($TargetProcess) {
    foreach ($Proc in $TargetProcess) {
        Write-Host "Terminating process (Name: $($Proc.ProcessName) | PID: $($Proc.Id))..." -ForegroundColor Yellow
        try {
            $Proc.Kill()
            # Wait up to 5 seconds to ensure resources (especially VRAM) are fully freed
            $Proc.WaitForExit(5000)
            Write-Host "Process stopped." -ForegroundColor Green
        } catch {
            Write-Error "Failed to terminate process PID $($Proc.Id): $_"
        }
    }
} else {
    Write-Host "No active llama-server processes found." -ForegroundColor Green
}

# 4. Clean up remaining state files
if (Test-Path $PidFile) {
    Remove-Item $PidFile -Force
    Write-Host "Cleaned up PID file: $PidFile" -ForegroundColor Cyan
}
