<#
Deploy the serverless stack, the frontend and the database migrations. Run from the project root after `aws login`:

    .\deploy\deploy.ps1                       # everything
    .\deploy\deploy.ps1 -FrontendOnly         # only re-upload frontend/ (seconds)

Settings that are not secret live in deploy/stack-params.json (copy deploy/stack-params.example.json).
The database URL is read from SSM Parameter Store (SecureString) and passed to the stack as a NoEcho parameter.
Needs: AWS CLI v2, Python 3.14 (.venv). No SAM CLI or Docker needed.
#>
param(
    [string]$Stack = "bureau-submissions",
    [string]$Region = "ap-south-1",
    [string]$ParamsFile = "deploy/stack-params.json",
    [switch]$FrontendOnly
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$p = Get-Content $ParamsFile -Raw | ConvertFrom-Json

function Invoke-Aws {
    $out = & aws @args --region $Region
    if ($LASTEXITCODE -ne 0) { throw "aws $($args -join ' ') failed" }
    return $out
}

function Get-Outputs {
    $raw = Invoke-Aws cloudformation describe-stacks --stack-name $Stack --query "Stacks[0].Outputs" --output json
    $map = @{}
    foreach ($o in ($raw | ConvertFrom-Json)) { $map[$o.OutputKey] = $o.OutputValue }
    return $map
}

if (-not $FrontendOnly) {
    # ---------------------------------------------------------------- 1. Lambda package (Linux wheels for python3.14)
    Write-Host "Building the Lambda package..."
    $build = Join-Path $root "build\lambda"
    if (Test-Path $build) { Remove-Item -LiteralPath $build -Recurse -Force }
    New-Item -ItemType Directory -Force $build | Out-Null
    Copy-Item -Recurse submissions, clients, migrations $build
    Get-ChildItem $build -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
    & .\.venv\Scripts\python -m pip install --quiet --target $build --platform manylinux2014_x86_64 `
        --implementation cp --python-version 3.14 --only-binary=:all: -r deploy\requirements-lambda.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install for the Lambda package failed" }

    # ---------------------------------------------------------------- 2. stack
    $dbUrl = Invoke-Aws ssm get-parameter --name $p.DatabaseUrlParameter --with-decryption --query Parameter.Value --output text
    Write-Host "Packaging and deploying stack $Stack..."
    Invoke-Aws cloudformation package --template-file template.yaml --s3-bucket $p.ArtifactBucket `
        --s3-prefix $p.ArtifactPrefix --output-template-file build\packaged.yaml | Out-Null
    $overrides = @(
        "SubnetIds=$($p.SubnetIds -join ',')", "LambdaSecurityGroupId=$($p.LambdaSecurityGroupId)",
        "FilesBucket=$($p.FilesBucket)", "FilesPrefix=$($p.FilesPrefix)", "AdminEmail=$($p.AdminEmail)",
        "CognitoDomainPrefix=$($p.CognitoDomainPrefix)", "DatabaseUrl=$dbUrl")
    Invoke-Aws cloudformation deploy --template-file build\packaged.yaml --stack-name $Stack `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset `
        --parameter-overrides @overrides
    $dbUrl = $null
}

# -------------------------------------------------------------------- 3. frontend (config.js from the stack outputs)
$out = Get-Outputs
Write-Host "Uploading the frontend to $($out.UiBucketName)..."
$site = Join-Path $root "build\frontend"
if (Test-Path $site) { Remove-Item -LiteralPath $site -Recurse -Force }
Copy-Item -Recurse frontend $site
@"
window.APP_CONFIG = {
  auth: "cognito",
  authority: "https://cognito-idp.$Region.amazonaws.com/$($out.UserPoolId)",
  clientId: "$($out.UserPoolClientId)",
  domain: "$($out.CognitoDomain)",
};
"@ | Set-Content -Encoding utf8 (Join-Path $site "config.js")
Invoke-Aws s3 sync $site "s3://$($out.UiBucketName)/" --delete --cache-control "no-cache" | Out-Null
Invoke-Aws cloudfront create-invalidation --distribution-id $out.DistributionId --paths "/*" | Out-Null

if (-not $FrontendOnly) {
    # ---------------------------------------------------------------- 4. database migrations, first app user
    function Invoke-Job([string]$json) {
        $file = Join-Path $root "build\job-result.json"
        Invoke-Aws lambda invoke --function-name $out.JobsFunctionName --cli-binary-format raw-in-base64-out `
            --payload $json $file | Out-Null
        return Get-Content $file -Raw
    }
    Write-Host "Migrations:" (Invoke-Job '{"job": "migrate"}')
    $admin = $p.AdminEmail.ToLower()
    $username = ($admin -split "@")[0]
    $result = Invoke-Job ('{"job": "users", "args": ["add", "' + $username + '", "--email", "' + $admin +
                          '", "--name", "' + $p.AdminName + '", "--admin"]}')
    if ($result -match "already exists") { Write-Host "Admin user: $username already registered" }
    else { Write-Host "Admin user:" $result }
}

Write-Host ""
Write-Host "App: $($out.AppUrl)"
Write-Host "Cognito sends the first sign-in e-mail (temporary password) to $($p.AdminEmail)."
