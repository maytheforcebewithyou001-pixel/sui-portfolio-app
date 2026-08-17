# Cloud Run Job (fc-history-record) + Cloud Scheduler (07:00 JST) deploy script.
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_history_job.ps1
# Creates/updates the daily asset-record job (api/history_job.py) and its scheduler.
# Idempotent: safe to re-run. ASCII only (PowerShell 5.1 safe).

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repo

$project = "wide-maxim-491005-q9"
$region = "asia-northeast1"
$job = "fc-history-record"
$scheduler = "fc-history-record-0700"
$sa = "344263534586-compute@developer.gserviceaccount.com"

Write-Host "[1/4] Enabling Cloud Scheduler API (idempotent) ..."
gcloud services enable cloudscheduler.googleapis.com --project $project | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "NG: enable API failed" -ForegroundColor Red; exit 1 }

Write-Host "[2/4] Deploying Cloud Run job from: $repo"
gcloud run jobs deploy $job `
  --source . `
  --project $project `
  --region $region `
  --command python `
  "--args=-m,api.history_job" `
  --set-secrets "GCP_CREDENTIALS_JSON=fc-gcp-creds:latest,FC_SHEET_IDS_JSON=fc-sheet-ids:latest,JQUANTS_API_KEY=fc-jquants-key:latest" `
  --set-env-vars "FC_API_USER=admin" `
  --task-timeout 600 `
  --max-retries 1
if ($LASTEXITCODE -ne 0) { Write-Host "NG: job deploy failed" -ForegroundColor Red; exit 1 }

Write-Host "[3/4] Granting run.invoker on the job to scheduler SA (idempotent) ..."
gcloud run jobs add-iam-policy-binding $job `
  --project $project `
  --region $region `
  --member "serviceAccount:$sa" `
  --role "roles/run.invoker" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "NG: IAM grant failed" -ForegroundColor Red; exit 1 }

Write-Host "[4/4] Creating/updating scheduler ($scheduler, 07:00 JST daily) ..."
$uri = "https://run.googleapis.com/v2/projects/$project/locations/$region/jobs/${job}:run"
gcloud scheduler jobs describe $scheduler --project $project --location $region 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $verb = "update" } else { $verb = "create" }
gcloud scheduler jobs $verb http $scheduler `
  --project $project `
  --location $region `
  --schedule "0 7 * * *" `
  --time-zone "Asia/Tokyo" `
  --uri $uri `
  --http-method POST `
  --oauth-service-account-email $sa
if ($LASTEXITCODE -ne 0) { Write-Host "NG: scheduler $verb failed" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "OK: job + scheduler deployed." -ForegroundColor Green
Write-Host "Test now (expects SKIP if today is already recorded):"
Write-Host "  gcloud run jobs execute $job --project $project --region $region --wait"
