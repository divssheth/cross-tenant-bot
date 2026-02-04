<#
.SYNOPSIS
    Creates Teams Bot and Copilot Agent app packages from templates.

.DESCRIPTION
    This script reads values from .env file and creates:
    - TeamsAppPackage/CrossTenantBot.zip (for Teams Bot)
    - CopilotAppPackage/CrossTenantAgent.zip (for Copilot Agent)

.NOTES
    Prerequisites:
    - .env file with AZURE_CLIENT_ID, GRAPH_APP_ID configured
    - Template manifest files in TeamsAppPackage and CopilotAppPackage

.EXAMPLE
    .\Create-AppPackages.ps1
    
.EXAMPLE
    .\Create-AppPackages.ps1 -TeamsOnly
    
.EXAMPLE
    .\Create-AppPackages.ps1 -CopilotOnly
#>

param(
    [switch]$TeamsOnly,
    [switch]$CopilotOnly
)

# =============================================================================
# CONFIGURATION
# =============================================================================

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$envFile = Join-Path $rootDir ".env"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Step {
    param([string]$Message)
    Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "  $Message" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Yellow
}

function Get-EnvValue {
    param([string]$Key)
    
    if (-not (Test-Path $envFile)) {
        Write-Error "❌ .env file not found at: $envFile"
        return $null
    }
    
    $content = Get-Content $envFile -Raw
    if ($content -match "$Key=(.+)") {
        return $matches[1].Trim()
    }
    return $null
}

# =============================================================================
# PACKAGE CREATION FUNCTIONS
# =============================================================================

function New-TeamsPackage {
    <#
    .SYNOPSIS
        Creates the Teams Bot app package (CrossTenantBot.zip)
    #>
    
    Write-Step "Creating Teams Bot Package"
    
    $teamsDir = Join-Path $rootDir "TeamsAppPackage"
    $outputDir = Join-Path $teamsDir "output"
    $templateFile = Join-Path $teamsDir "manifest.json"
    $zipFile = Join-Path $teamsDir "CrossTenantBot.zip"
    
    # Get values from .env
    $azureClientId = Get-EnvValue "AZURE_CLIENT_ID"
    $graphAppId = Get-EnvValue "GRAPH_APP_ID"
    
    if (-not $azureClientId) {
        Write-Error "❌ AZURE_CLIENT_ID not found in .env"
        return
    }
    
    Write-Info "AZURE_CLIENT_ID: $azureClientId"
    Write-Info "GRAPH_APP_ID: $graphAppId"
    
    # Create output directory
    if (-not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    
    # Read template and replace placeholders
    $manifest = Get-Content $templateFile -Raw
    $manifest = $manifest -replace 'YOUR-TEAMS-APP-GUID', $azureClientId
    $manifest = $manifest -replace 'YOUR-UAMI-CLIENT-ID', $azureClientId
    $manifest = $manifest -replace 'YOUR-GRAPH-APP-ID', $graphAppId
    $manifest = $manifest -replace 'YOUR-CONTAINER-APP-DOMAIN', ''
    
    # Save manifest
    $manifest | Set-Content (Join-Path $outputDir "manifest.json") -Encoding UTF8
    
    # Copy icons
    Copy-Item (Join-Path $teamsDir "color.png") (Join-Path $outputDir "color.png") -Force
    Copy-Item (Join-Path $teamsDir "outline.png") (Join-Path $outputDir "outline.png") -Force
    
    # Create ZIP
    if (Test-Path $zipFile) { Remove-Item $zipFile -Force }
    Compress-Archive -Path "$outputDir\*" -DestinationPath $zipFile -Force
    
    Write-Success "Created: $zipFile"
    Write-Host ""
    Write-Host "Package contents:" -ForegroundColor White
    Write-Host "  • manifest.json (Bot ID: $azureClientId)" -ForegroundColor Gray
    Write-Host "  • color.png" -ForegroundColor Gray
    Write-Host "  • outline.png" -ForegroundColor Gray
}

function New-CopilotPackage {
    <#
    .SYNOPSIS
        Creates the Copilot Agent app package (CrossTenantAgent.zip)
    #>
    
    Write-Step "Creating Copilot Agent Package"
    
    $copilotDir = Join-Path $rootDir "CopilotAppPackage"
    $outputDir = Join-Path $copilotDir "output"
    $templateFile = Join-Path $copilotDir "manifest.template.json"
    $zipFile = Join-Path $copilotDir "CrossTenantAgent.zip"
    
    # Get values from .env
    $azureClientId = Get-EnvValue "AZURE_CLIENT_ID"
    
    if (-not $azureClientId) {
        Write-Error "❌ AZURE_CLIENT_ID not found in .env"
        return
    }
    
    Write-Info "AZURE_CLIENT_ID: $azureClientId"
    
    # Create output directory
    if (-not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    
    # Read template and replace placeholders
    $manifest = Get-Content $templateFile -Raw
    $manifest = $manifest -replace '\$\{AZURE_CLIENT_ID\}', $azureClientId
    
    # Save manifest
    $manifest | Set-Content (Join-Path $outputDir "manifest.json") -Encoding UTF8
    
    # Copy icons
    Copy-Item (Join-Path $copilotDir "color.png") (Join-Path $outputDir "color.png") -Force
    Copy-Item (Join-Path $copilotDir "outline.png") (Join-Path $outputDir "outline.png") -Force
    
    # Create ZIP
    if (Test-Path $zipFile) { Remove-Item $zipFile -Force }
    Compress-Archive -Path "$outputDir\*" -DestinationPath $zipFile -Force
    
    Write-Success "Created: $zipFile"
    Write-Host ""
    Write-Host "Package contents:" -ForegroundColor White
    Write-Host "  • manifest.json (Agent ID: $azureClientId)" -ForegroundColor Gray
    Write-Host "  • color.png" -ForegroundColor Gray
    Write-Host "  • outline.png" -ForegroundColor Gray
    Write-Host ""
    Write-Host "⚠️  Requirements for Copilot Agent:" -ForegroundColor Yellow
    Write-Host "  • App registration must be MULTI-TENANT" -ForegroundColor Yellow
    Write-Host "  • Users need Microsoft 365 Copilot license" -ForegroundColor Yellow
}

# =============================================================================
# MAIN
# =============================================================================

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║           Teams & Copilot App Package Creator              ║" -ForegroundColor Magenta
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Magenta

if ($CopilotOnly) {
    New-CopilotPackage
} elseif ($TeamsOnly) {
    New-TeamsPackage
} else {
    New-TeamsPackage
    New-CopilotPackage
}

Write-Host ""
Write-Host "Done! Upload the .zip files to Teams Admin Center or sideload directly." -ForegroundColor Green
Write-Host ""
