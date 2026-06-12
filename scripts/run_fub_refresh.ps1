# run_fub_refresh.ps1 — Task Scheduler entry point for the FUB warehouse refresh
# (Windows equivalent of the macOS launchd job). Runs refresh_daily.py:
# extract -> audit -> integrity -> manifest -> load_to_sql -> views -> smoke.
#
# PRE-REQ: GHL_SQL_* in .env must point at a live warehouse (currently they
# don't — the scheduled task ships DISABLED; enable it when the VM exists:
#   Enable-ScheduledTask -TaskName "FUB Warehouse Refresh"
#
# Logs to logs\refresh-YYYYMMDD-HHmm.log. Exit code = refresh_daily's.

param([switch]$DryRun)

$env:PYTHONUTF8 = "1"
$root = "C:\Users\vjpov\Codebase\FUB_API"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("refresh-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".log")

Set-Location $root
$flags = @()
if ($DryRun) { $flags += "--dry-run" }
& python -u scripts\refresh_daily.py @flags *> $log
$code = $LASTEXITCODE
Add-Content -Path $log -Value "`n[wrapper] exit code: $code"
exit $code
