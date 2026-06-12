# run_fub_push.ps1 — Task Scheduler entry point for the FUB lead push.
# Runs scripts\push_all_to_fub.py: Niche foreclosures ONLY ->
# upserted into the live FUB CRM (idempotent via the ledger). Fires at
# 9:00 / 15:00 / 21:00, 30 min after the RPRD lead scrape (8:30/14:30/20:30).
#
# RPRD push DISABLED 2026-06-10 on founder request: RPRD leads have no phone
# numbers and must be skip-traced (DataSift) + relevance-filtered before any
# FUB import. Founder deleted all 10,217 previously pushed RPRD leads.
# Do NOT remove --only niche until the skip-trace workflow is in place.
#
# Default is LIVE (--push). Pass -DryRun to log the bodies and write nothing.
# Logs to logs\push-YYYYMMDD-HHmm.log. Exit code = push_all_to_fub's.

param([switch]$DryRun)

$env:PYTHONUTF8 = "1"
$root = "C:\Users\vjpov\Codebase\FUB_API"
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("push-" + (Get-Date -Format "yyyyMMdd-HHmm") + ".log")

Set-Location $root
$flags = @("--only", "niche")
if (-not $DryRun) { $flags += "--push" }
& python -u scripts\push_all_to_fub.py @flags *> $log
$code = $LASTEXITCODE

# RPRD leads -> DataSift skip-trace CSV (delta only; replaces the FUB push for
# RPRD). New batches land in data\exports\skiptrace\ for manual upload.
& python -u scripts\export_skiptrace_csv.py *>> $log
if ($LASTEXITCODE -ne 0 -and $code -eq 0) { $code = $LASTEXITCODE }

Add-Content -Path $log -Value "`n[wrapper] exit code: $code"
exit $code
