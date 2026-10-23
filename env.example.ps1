# Local development. Copy to env.ps1, fill in, and load it in EVERY terminal before starting the API or the worker:
#   . .\env.ps1
# The API and the worker must share these settings (same database, same file storage).
# env.ps1 holds a password: keep it out of source control. (On AWS the settings come from the stack: RUNBOOK.md.)

$env:SUBMISSIONS_DATABASE_URL  = "mysql+pymysql://<user>:<url-encoded-password>@<host>:3306/my_demo_db"

# Generated files: "local" (folder SUBMISSIONS_OUTPUT_DIR, default output/) or AWS S3 (credentials from `aws login`)
$env:SUBMISSIONS_STORAGE       = "local"
# $env:SUBMISSIONS_STORAGE     = "s3"
# $env:SUBMISSIONS_S3_BUCKET   = "opta-s3-demo"
# $env:SUBMISSIONS_S3_PREFIX   = "bureau-submissions"
# $env:SUBMISSIONS_S3_REGION   = "ap-south-1"

# No sign-in locally (on AWS: Cognito), and the API also serves the pages from frontend/
$env:SUBMISSIONS_AUTH          = "none"
$env:SUBMISSIONS_FRONTEND_DIR  = "frontend"
