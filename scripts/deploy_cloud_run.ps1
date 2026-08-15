# Cloud Run (fc-api) deploy script - run from anywhere:
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_cloud_run.ps1
# Adds multi-user secrets (FC_AUTH_USERS_JSON / FC_SHEET_IDS_JSON) on top of
# existing env/secrets (--update-secrets merges, does not replace).
# ASCII only (PowerShell 5.1 safe).

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo

# Grant runtime SA access to the multi-user secrets (idempotent; needed once).
$sa = "serviceAccount:344263534586-compute@developer.gserviceaccount.com"
foreach ($sec in @("fc-auth-users", "fc-sheet-ids")) {
  Write-Host "Granting secretAccessor on $sec ..."
  gcloud secrets add-iam-policy-binding $sec `
    --member $sa `
    --role "roles/secretmanager.secretAccessor" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "NG: IAM grant failed on $sec" -ForegroundColor Red
    exit 1
  }
}

Write-Host "Deploying fc-api from: $repo"

gcloud run deploy fc-api `
  --source . `
  --region asia-northeast1 `
  --update-secrets "FC_AUTH_USERS_JSON=fc-auth-users:latest,FC_SHEET_IDS_JSON=fc-sheet-ids:latest"

if ($LASTEXITCODE -eq 0) {
  Write-Host "OK: deploy finished." -ForegroundColor Green
} else {
  Write-Host "NG: deploy failed (exit $LASTEXITCODE). Paste the error above to Claude." -ForegroundColor Red
}
