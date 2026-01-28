# Create-TeamsPackage.ps1
# Creates Teams app package from template, replacing placeholders with values from .env file
# Uses ENABLE_RSC flag from .env to determine which template to use
# Location: devTools/Create-TeamsPackage.ps1
#
# Part of the Cross-Tenant Teams Bot modular architecture.
# See app/README.md for customization instructions.

param(
    [Parameter(Mandatory=$false)]
    [string]$EnvFile,
    
    [Parameter(Mandatory=$false)]
    [string]$OutputPath,
    
    [Parameter(Mandatory=$false)]
    [switch]$Silent
)

# Get the project root (parent of devTools)
$ProjectRoot = Split-Path $PSScriptRoot -Parent

# Set defaults relative to project root
if (-not $EnvFile) {
    $EnvFile = Join-Path $ProjectRoot ".env"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $ProjectRoot "TeamsAppPackage\output"
}

$ErrorActionPreference = "Stop"

if (-not $Silent) {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  Teams App Package Generator" -ForegroundColor Cyan
    Write-Host "  Cross-Tenant Bot - Modular Architecture" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

# Function to parse .env file
function Get-EnvFileContent {
    param([string]$Path)
    
    $envVars = @{}
    
    if (-not (Test-Path $Path)) {
        Write-Error "Environment file not found: $Path"
        return $null
    }
    
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        
        # Skip comments and empty lines
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line -split "=", 2
            if ($parts.Count -eq 2) {
                $key = $parts[0].Trim()
                $value = $parts[1].Trim()
                # Remove surrounding quotes if present
                $value = $value -replace '^["'']|["'']$', ''
                $envVars[$key] = $value
            }
        }
    }
    
    return $envVars
}

# Load environment variables from .env file
Write-Host "Loading configuration from: $EnvFile" -ForegroundColor Yellow
$envVars = Get-EnvFileContent -Path $EnvFile

if (-not $envVars) {
    Write-Error "Failed to load environment file"
    exit 1
}

# Determine if RSC is enabled
$enableRsc = $envVars["ENABLE_RSC"] -eq "true"

Write-Host ""
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  RSC Enabled: $enableRsc"

# Select the appropriate template from TeamsAppPackage folder
$templateFolder = Join-Path $ProjectRoot "TeamsAppPackage"
if ($enableRsc) {
    $templateFile = Join-Path $templateFolder "manifest.rsc.template.json"
    Write-Host "  Template: manifest.rsc.template.json (with RSC)" -ForegroundColor Green
} else {
    $templateFile = Join-Path $templateFolder "manifest.template.json"
    Write-Host "  Template: manifest.template.json (without RSC)" -ForegroundColor Green
}

if (-not (Test-Path $templateFile)) {
    Write-Error "Template file not found: $templateFile"
    exit 1
}

# Define placeholder mappings from env vars
# Format: PlaceholderName = @{ EnvVar = "ENV_VAR_NAME"; Default = "default value" }
$placeholderMappings = @{
    "BOT_APP_ID" = @{ EnvVar = "MICROSOFT_APP_ID"; Default = "" }
    "GRAPH_APP_ID" = @{ EnvVar = "GRAPH_APP_ID"; Default = "" }
    "VALID_DOMAIN" = @{ EnvVar = "CONTAINER_APP_DOMAIN"; Default = "your-app.azurecontainerapps.io" }
    "APP_VERSION" = @{ EnvVar = "APP_VERSION"; Default = "1.0.0" }
    "PACKAGE_NAME" = @{ EnvVar = "PACKAGE_NAME"; Default = "com.contoso.crosstenantbot" }
    "DEVELOPER_NAME" = @{ EnvVar = "DEVELOPER_NAME"; Default = "Your Company" }
    "DEVELOPER_WEBSITE_URL" = @{ EnvVar = "DEVELOPER_WEBSITE_URL"; Default = "https://example.com" }
    "DEVELOPER_PRIVACY_URL" = @{ EnvVar = "DEVELOPER_PRIVACY_URL"; Default = "https://example.com/privacy" }
    "DEVELOPER_TERMS_URL" = @{ EnvVar = "DEVELOPER_TERMS_URL"; Default = "https://example.com/terms" }
    "APP_SHORT_NAME" = @{ EnvVar = "APP_SHORT_NAME"; Default = "CrossTenant Bot" }
    "APP_FULL_NAME" = @{ EnvVar = "APP_FULL_NAME"; Default = "Cross-Tenant AI Bot" }
    "APP_SHORT_DESCRIPTION" = @{ EnvVar = "APP_SHORT_DESCRIPTION"; Default = "AI-powered Teams bot for cross-tenant collaboration" }
    "APP_FULL_DESCRIPTION" = @{ EnvVar = "APP_FULL_DESCRIPTION"; Default = "A Teams bot that works across tenants with AI-powered responses." }
    "ACCENT_COLOR" = @{ EnvVar = "ACCENT_COLOR"; Default = "#5558AF" }
}

# Read template content
Write-Host ""
Write-Host "Processing template..." -ForegroundColor Yellow
$manifestContent = Get-Content $templateFile -Raw

# Replace placeholders
$replacements = @{}
foreach ($placeholder in $placeholderMappings.Keys) {
    $mapping = $placeholderMappings[$placeholder]
    $envVarName = $mapping.EnvVar
    $defaultValue = $mapping.Default
    
    # Get value from env vars or use default
    $value = if ($envVars.ContainsKey($envVarName) -and $envVars[$envVarName]) {
        $envVars[$envVarName]
    } else {
        $defaultValue
    }
    
    $replacements[$placeholder] = $value
    $manifestContent = $manifestContent -replace "\{\{$placeholder\}\}", $value
}

# Validate required values
$requiredFields = @("BOT_APP_ID", "VALID_DOMAIN")
if ($enableRsc) {
    $requiredFields += "GRAPH_APP_ID"
}

$missingFields = @()
foreach ($field in $requiredFields) {
    if (-not $replacements[$field]) {
        $missingFields += $field
    }
}

if ($missingFields.Count -gt 0) {
    Write-Host ""
    Write-Warning "Missing required values for: $($missingFields -join ', ')"
    Write-Host "Please ensure these are set in your .env file:" -ForegroundColor Yellow
    foreach ($field in $missingFields) {
        $envVarName = $placeholderMappings[$field].EnvVar
        Write-Host "  - $envVarName" -ForegroundColor Yellow
    }
    Write-Host ""
}

# Show resolved values
Write-Host ""
Write-Host "Resolved values:" -ForegroundColor Yellow
Write-Host "  Bot App ID: $($replacements['BOT_APP_ID'])"
Write-Host "  Valid Domain: $($replacements['VALID_DOMAIN'])"
if ($enableRsc) {
    Write-Host "  Graph App ID: $($replacements['GRAPH_APP_ID'])"
}
Write-Host "  App Name: $($replacements['APP_SHORT_NAME'])"

# Ensure output directory exists
if (-not (Test-Path $OutputPath)) {
    New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
}

# Write manifest
$manifestPath = Join-Path $OutputPath "manifest.json"
Set-Content -Path $manifestPath -Value $manifestContent -Encoding UTF8
Write-Host ""
Write-Host "Created: $manifestPath" -ForegroundColor Green

# Copy icons from TeamsAppPackage folder
$colorIconSource = Join-Path $templateFolder "color.png"
$outlineIconSource = Join-Path $templateFolder "outline.png"
$colorIconDest = Join-Path $OutputPath "color.png"
$outlineIconDest = Join-Path $OutputPath "outline.png"

if (Test-Path $colorIconSource) {
    Copy-Item $colorIconSource $colorIconDest -Force
    Write-Host "Copied: color.png (192x192)" -ForegroundColor Green
} else {
    Write-Warning "color.png not found in TeamsAppPackage folder. Please add a 192x192 PNG icon."
}

if (Test-Path $outlineIconSource) {
    Copy-Item $outlineIconSource $outlineIconDest -Force
    Write-Host "Copied: outline.png (32x32)" -ForegroundColor Green
} else {
    Write-Warning "outline.png not found in TeamsAppPackage folder. Please add a 32x32 PNG icon."
}

# Create ZIP package
$zipFileName = if ($enableRsc) { "TeamsBot-RSC.zip" } else { "TeamsBot.zip" }
$zipPath = Join-Path (Split-Path $OutputPath -Parent) $zipFileName

# Remove existing zip if present
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

# Create zip
Write-Host ""
Write-Host "Creating package: $zipPath" -ForegroundColor Yellow
Compress-Archive -Path "$OutputPath\*" -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Package created successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Output files:" -ForegroundColor Yellow
Write-Host "  Manifest: $manifestPath"
Write-Host "  Package:  $zipPath"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Go to Teams Admin Center or Teams Developer Portal"
Write-Host "  2. Upload the package: $zipPath"
Write-Host "  3. Install the app to your team/users"
Write-Host ""

if (-not $enableRsc) {
    Write-Host "Note: RSC is disabled (ENABLE_RSC=false in .env)." -ForegroundColor Cyan
    Write-Host "      The bot will work in all scopes but channel message" -ForegroundColor Cyan
    Write-Host "      history will not be available." -ForegroundColor Cyan
} else {
    Write-Host "Note: RSC is enabled (ENABLE_RSC=true in .env)." -ForegroundColor Cyan
    Write-Host "      Make sure:" -ForegroundColor Cyan
    Write-Host "      1. GRAPH_APP_ID is a multi-tenant app registration" -ForegroundColor Cyan
    Write-Host "      2. The app has ChannelMessage.Read.Group RSC permission" -ForegroundColor Cyan
    Write-Host "      3. The target tenant allows RSC permissions" -ForegroundColor Cyan
}

Write-Host ""
return $zipPath
