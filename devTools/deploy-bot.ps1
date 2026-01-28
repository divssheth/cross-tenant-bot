<#
.SYNOPSIS
    Deploys and manages a Cross-Tenant Teams Bot with User Assigned Managed Identity (UAMI) on Azure Container Apps.

.DESCRIPTION
    This script provides functions to:
    - Deploy the complete infrastructure (ACR, Container Apps Environment, Container App)
    - Redeploy/update the bot code to the existing Container App
    - Verify the deployment and configuration
    - Create Teams app packages
    - Troubleshoot common issues

    The bot uses UAMI for authentication which eliminates the need for client secrets.
    Configuration is read from .env file in project root.

.NOTES
    Author: Divyesh
    Created: January 2026
    
    Prerequisites:
    - Azure CLI installed and logged in (az login)
    - Docker installed (for local builds only)
    - Appropriate Azure permissions (Contributor on resource group)

.EXAMPLE
    # Full deployment
    .\deploy-bot.ps1
    Deploy-BotInfrastructure

.EXAMPLE
    # Redeploy code only
    .\deploy-bot.ps1
    Redeploy-BotCode -ImageTag "v3"

.EXAMPLE
    # Create Teams package
    .\deploy-bot.ps1
    Create-TeamsPackage

.EXAMPLE
    # Verify deployment
    .\deploy-bot.ps1
    Verify-BotDeployment
#>

# =============================================================================
# CONFIGURATION VARIABLES
# =============================================================================

# Get project root (parent of devTools)
$script:PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
$script:ENV_FILE = Join-Path $script:PROJECT_ROOT ".env"

# Function to load configuration from .env file
function Get-EnvConfig {
    <#
    .SYNOPSIS
        Loads configuration from .env file.
    #>
    $config = @{}
    
    if (Test-Path $script:ENV_FILE) {
        Get-Content $script:ENV_FILE | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                $parts = $line -split "=", 2
                if ($parts.Count -eq 2) {
                    $key = $parts[0].Trim()
                    $value = $parts[1].Trim() -replace '^["'']|["'']$', ''
                    $config[$key] = $value
                }
            }
        }
        Write-Host "Loaded configuration from: $($script:ENV_FILE)" -ForegroundColor Gray
    } else {
        Write-Warning ".env file not found at: $($script:ENV_FILE)"
    }
    
    return $config
}

# Load configuration
$script:EnvConfig = Get-EnvConfig

# Resource Group & Location (from .env or defaults)
$script:RESOURCE_GROUP = if ($script:EnvConfig["RESOURCE_GROUP"]) { $script:EnvConfig["RESOURCE_GROUP"] } else { "tesco-bot-rg" }
$script:LOCATION = if ($script:EnvConfig["AZURE_LOCATION"]) { $script:EnvConfig["AZURE_LOCATION"] } else { "eastus" }

# Azure Container Registry
$script:ACR_NAME = if ($script:EnvConfig["ACR_NAME"]) { $script:EnvConfig["ACR_NAME"] } else { "crosstenantbotacr" }

# Container Apps
$script:CONTAINER_ENV_NAME = if ($script:EnvConfig["CONTAINER_ENV_NAME"]) { $script:EnvConfig["CONTAINER_ENV_NAME"] } else { "crosstenant-bot-env" }
$script:CONTAINER_APP_NAME = if ($script:EnvConfig["CONTAINER_APP_NAME"]) { $script:EnvConfig["CONTAINER_APP_NAME"] } else { "crosstenant-bot-app" }

# User Assigned Managed Identity
$script:UAMI_NAME = if ($script:EnvConfig["UAMI_NAME"]) { $script:EnvConfig["UAMI_NAME"] } else { "tescobot" }

# Bot Configuration
$script:BOT_NAME = if ($script:EnvConfig["BOT_NAME"]) { $script:EnvConfig["BOT_NAME"] } else { "tescobotdivnp" }
$script:BOT_APP_ID = if ($script:EnvConfig["MICROSOFT_APP_ID"]) { $script:EnvConfig["MICROSOFT_APP_ID"] } else { "" }

# Feature Flags
$script:ENABLE_RSC = $script:EnvConfig["ENABLE_RSC"] -eq "true"
$script:ENABLE_AI = $script:EnvConfig["ENABLE_AI"] -ne "false"  # Default true

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Step {
    <#
    .SYNOPSIS
        Writes a formatted step message to the console.
    #>
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

function Write-Error {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Get-UamiDetails {
    <#
    .SYNOPSIS
        Retrieves UAMI details (ID, Client ID, Principal ID).
    #>
    $uamiId = az identity show --name $script:UAMI_NAME --resource-group $script:RESOURCE_GROUP --query id -o tsv
    $uamiClientId = az identity show --name $script:UAMI_NAME --resource-group $script:RESOURCE_GROUP --query clientId -o tsv
    $uamiPrincipalId = az identity show --name $script:UAMI_NAME --resource-group $script:RESOURCE_GROUP --query principalId -o tsv
    
    return @{
        Id = $uamiId
        ClientId = $uamiClientId
        PrincipalId = $uamiPrincipalId
    }
}

function Get-AcrDetails {
    <#
    .SYNOPSIS
        Retrieves ACR details (Login Server, Resource ID).
    #>
    $loginServer = az acr show --name $script:ACR_NAME --query loginServer -o tsv
    $acrId = az acr show --name $script:ACR_NAME --query id -o tsv
    
    return @{
        LoginServer = $loginServer
        Id = $acrId
    }
}

# =============================================================================
# DEPLOYMENT FUNCTIONS
# =============================================================================

function Deploy-BotInfrastructure {
    <#
    .SYNOPSIS
        Deploys the complete bot infrastructure from scratch.
    
    .DESCRIPTION
        This function performs the following steps:
        1. Creates Azure Container Registry (ACR)
        2. Builds and pushes the Docker image
        3. Creates Container Apps Environment
        4. Assigns AcrPull role to UAMI
        5. Creates Container App with UAMI
    
    .PARAMETER ImageTag
        The tag for the Docker image. Defaults to "v1".
    
    .EXAMPLE
        Deploy-BotInfrastructure -ImageTag "v1"
    #>
    param(
        [string]$ImageTag = "v1"
    )

    Write-Step "Step 1: Creating Azure Container Registry"
    az acr create `
        --name $script:ACR_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --sku Basic `
        --admin-enabled true
    
    if ($LASTEXITCODE -eq 0) { Write-Success "ACR created: $script:ACR_NAME" }
    else { Write-Error "Failed to create ACR"; return }

    # Get ACR details
    $acr = Get-AcrDetails
    Write-Info "ACR Login Server: $($acr.LoginServer)"

    Write-Step "Step 2: Building Docker Image in ACR"
    az acr build `
        --registry $script:ACR_NAME `
        --image "crosstenant-bot:$ImageTag" `
        .
    
    if ($LASTEXITCODE -eq 0) { Write-Success "Image built: crosstenant-bot:$ImageTag" }
    else { Write-Error "Failed to build image"; return }

    Write-Step "Step 3: Creating Container Apps Environment"
    az containerapp env create `
        --name $script:CONTAINER_ENV_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --location $script:LOCATION
    
    if ($LASTEXITCODE -eq 0) { Write-Success "Environment created: $script:CONTAINER_ENV_NAME" }
    else { Write-Error "Failed to create environment"; return }

    # Get UAMI details
    $uami = Get-UamiDetails
    Write-Info "UAMI Client ID: $($uami.ClientId)"

    Write-Step "Step 4: Assigning AcrPull Role to UAMI"
    az role assignment create `
        --assignee $uami.PrincipalId `
        --role "AcrPull" `
        --scope $acr.Id
    
    if ($LASTEXITCODE -eq 0) { Write-Success "AcrPull role assigned" }
    else { Write-Info "Role may already exist (non-fatal)" }

    # Get tenant ID
    $tenantId = az account show --query tenantId -o tsv

    Write-Step "Step 5: Creating Container App"
    
    # Build environment variables list
    $envVarsList = @(
        "LOCAL_DEBUG=false",
        "AZURE_CLIENT_ID=$($uami.ClientId)",
        "AZURE_TENANT_ID=$tenantId",
        "MICROSOFT_APP_ID=$script:BOT_APP_ID",
        "CONTAINER_APP_NAME=$script:CONTAINER_APP_NAME",
        "ENABLE_RSC=$($script:ENABLE_RSC.ToString().ToLower())",
        "ENABLE_AI=$($script:ENABLE_AI.ToString().ToLower())"
    )
    
    # Add AI configuration if enabled
    if ($script:ENABLE_AI -and $script:EnvConfig["AZURE_AI_PROJECT_ENDPOINT"]) {
        $envVarsList += "AZURE_AI_PROJECT_ENDPOINT=$($script:EnvConfig['AZURE_AI_PROJECT_ENDPOINT'])"
        $envVarsList += "AZURE_AI_MODEL_DEPLOYMENT=$($script:EnvConfig['AZURE_AI_MODEL_DEPLOYMENT'])"
    }
    
    # Add RSC configuration if enabled
    if ($script:ENABLE_RSC) {
        if ($script:EnvConfig["GRAPH_APP_ID"]) {
            $envVarsList += "GRAPH_APP_ID=$($script:EnvConfig['GRAPH_APP_ID'])"
        }
        if ($script:EnvConfig["KEY_VAULT_NAME"]) {
            $envVarsList += "KEY_VAULT_NAME=$($script:EnvConfig['KEY_VAULT_NAME'])"
        }
    }
    
    az containerapp create `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --environment $script:CONTAINER_ENV_NAME `
        --image "$($acr.LoginServer)/crosstenant-bot:$ImageTag" `
        --target-port 3978 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 3 `
        --user-assigned $uami.Id `
        --registry-server $acr.LoginServer `
        --registry-identity $uami.Id `
        --set-env-vars @envVarsList
    
    if ($LASTEXITCODE -eq 0) { 
        Write-Success "Container App created: $script:CONTAINER_APP_NAME"
        
        # Get the FQDN
        $fqdn = az containerapp show `
            --name $script:CONTAINER_APP_NAME `
            --resource-group $script:RESOURCE_GROUP `
            --query "properties.configuration.ingress.fqdn" -o tsv
        
        Write-Host "`n" -NoNewline
        Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "║  DEPLOYMENT COMPLETE!                                         ║" -ForegroundColor Green
        Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "║  Bot Endpoint: https://$fqdn/api/messages" -ForegroundColor Green
        Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    }
    else { 
        Write-Error "Failed to create Container App"
    }
}

function Redeploy-BotCode {
    <#
    .SYNOPSIS
        Rebuilds the Docker image and updates the Container App.
    
    .DESCRIPTION
        Use this function to deploy code changes without recreating infrastructure.
        It will:
        1. Build a new Docker image in ACR
        2. Update the Container App to use the new image
    
    .PARAMETER ImageTag
        The tag for the new Docker image. Defaults to timestamp-based tag.
    
    .EXAMPLE
        Redeploy-BotCode
        # Uses auto-generated tag like "v20260121-143052"
    
    .EXAMPLE
        Redeploy-BotCode -ImageTag "v3"
        # Uses specific tag "v3"
    #>
    param(
        [string]$ImageTag = "v$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    )

    Write-Step "Redeploying Bot Code"
    Write-Info "Image Tag: $ImageTag"

    # Get ACR details
    $acr = Get-AcrDetails
    if (-not $acr.LoginServer) {
        Write-Error "Could not get ACR details. Is '$script:ACR_NAME' deployed?"
        return
    }

    Write-Step "Step 1: Building New Docker Image"
    az acr build `
        --registry $script:ACR_NAME `
        --image "crosstenant-bot:$ImageTag" `
        .
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to build image"
        return
    }
    Write-Success "Image built: crosstenant-bot:$ImageTag"

    Write-Step "Step 2: Updating Container App"
    az containerapp update `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --image "$($acr.LoginServer)/crosstenant-bot:$ImageTag"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Container App updated to image: crosstenant-bot:$ImageTag"
        
        # Get the FQDN
        $fqdn = az containerapp show `
            --name $script:CONTAINER_APP_NAME `
            --resource-group $script:RESOURCE_GROUP `
            --query "properties.configuration.ingress.fqdn" -o tsv
        
        Write-Host "`n" -NoNewline
        Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "║  REDEPLOYMENT COMPLETE!                                       ║" -ForegroundColor Green
        Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Green
        Write-Host "║  Image: crosstenant-bot:$ImageTag" -ForegroundColor Green
        Write-Host "║  Bot Endpoint: https://$fqdn/api/messages" -ForegroundColor Green
        Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    }
    else {
        Write-Error "Failed to update Container App"
    }
}

function Update-BotEnvironmentVariables {
    <#
    .SYNOPSIS
        Updates the environment variables on the Container App.
    
    .DESCRIPTION
        Use this to update environment variables without rebuilding the image.
        Reads from env.prod file if it exists.
    
    .PARAMETER EnvFile
        Path to the environment file. Defaults to "env.prod".
    
    .EXAMPLE
        Update-BotEnvironmentVariables -EnvFile "env.prod"
    #>
    param(
        [string]$EnvFile = "env.prod"
    )

    Write-Step "Updating Environment Variables"

    if (-not (Test-Path $EnvFile)) {
        Write-Error "Environment file not found: $EnvFile"
        return
    }

    # Parse env file and build env-vars string
    $envVars = @()
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        # Skip comments and empty lines
        if ($line -and -not $line.StartsWith("#")) {
            $envVars += $line
        }
    }

    $envVarsString = $envVars -join " "
    Write-Info "Found $($envVars.Count) environment variables"

    az containerapp update `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --set-env-vars $envVars

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Environment variables updated"
    }
    else {
        Write-Error "Failed to update environment variables"
    }
}

# =============================================================================
# VERIFICATION FUNCTIONS
# =============================================================================

function Verify-BotDeployment {
    <#
    .SYNOPSIS
        Verifies the bot deployment and displays configuration details.
    
    .DESCRIPTION
        Checks:
        - Azure Bot configuration
        - UAMI assignment
        - Container App identity
        - App Registration
        - Environment variables
    
    .EXAMPLE
        Verify-BotDeployment
    #>
    
    Write-Step "Verifying Bot Deployment"

    # 1. Check Azure Bot configuration
    Write-Info "Checking Azure Bot configuration..."
    $botConfig = az bot show `
        --name $script:BOT_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --query "{appId: properties.msaAppId, appType: properties.msaAppType, endpoint: properties.endpoint}" `
        -o json 2>$null | ConvertFrom-Json
    
    if ($botConfig) {
        Write-Success "Azure Bot found"
        Write-Host "   App ID: $($botConfig.appId)"
        Write-Host "   App Type: $($botConfig.appType)"
        Write-Host "   Endpoint: $($botConfig.endpoint)"
    }
    else {
        Write-Error "Azure Bot not found: $script:BOT_NAME"
    }

    # 2. Verify UAMI exists
    Write-Info "Checking UAMI..."
    $uami = Get-UamiDetails
    if ($uami.ClientId) {
        Write-Success "UAMI found: $script:UAMI_NAME"
        Write-Host "   Client ID: $($uami.ClientId)"
        Write-Host "   Principal ID: $($uami.PrincipalId)"
    }
    else {
        Write-Error "UAMI not found: $script:UAMI_NAME"
    }

    # 3. Check Container App has UAMI assigned
    Write-Info "Checking Container App identity..."
    $appIdentity = az containerapp identity show `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        -o json 2>$null | ConvertFrom-Json
    
    if ($appIdentity.userAssignedIdentities) {
        Write-Success "Container App has user-assigned identity"
    }
    else {
        Write-Error "Container App missing user-assigned identity"
    }

    # 4. Verify the App Registration exists
    Write-Info "Checking App Registration..."
    $appReg = az ad app show --id $script:BOT_APP_ID -o json 2>$null | ConvertFrom-Json
    if ($appReg) {
        Write-Success "App Registration found"
        Write-Host "   Display Name: $($appReg.displayName)"
    }
    else {
        Write-Error "App Registration not found: $script:BOT_APP_ID"
    }

    # 5. Check environment variables
    Write-Info "Checking Container App environment variables..."
    $envVars = az containerapp show `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --query "properties.template.containers[0].env" `
        -o json 2>$null | ConvertFrom-Json
    
    if ($envVars) {
        Write-Success "Environment variables configured:"
        $envVars | ForEach-Object {
            Write-Host "   $($_.name) = $($_.value)"
        }
    }

    # 6. Get full bot configuration
    Write-Info "Full Azure Bot MSA configuration:"
    az bot show `
        --name $script:BOT_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --query "{msaAppId:properties.msaAppId, msaAppType:properties.msaAppType, msaAppTenantId:properties.msaAppTenantId, msaAppMSIResourceId:properties.msaAppMSIResourceId}" `
        --output json 2>$null
}

function Get-BotLogs {
    <#
    .SYNOPSIS
        Retrieves the Container App logs for troubleshooting.
    
    .PARAMETER Follow
        If specified, follows the log stream.
    
    .PARAMETER Tail
        Number of lines to show. Defaults to 100.
    
    .EXAMPLE
        Get-BotLogs -Tail 50
    
    .EXAMPLE
        Get-BotLogs -Follow
    #>
    param(
        [switch]$Follow,
        [int]$Tail = 100
    )

    Write-Step "Retrieving Bot Logs"

    $params = @(
        "--name", $script:CONTAINER_APP_NAME,
        "--resource-group", $script:RESOURCE_GROUP,
        "--tail", $Tail
    )

    if ($Follow) {
        $params += "--follow"
        Write-Info "Streaming logs (Ctrl+C to stop)..."
    }

    az containerapp logs show @params
}

function Get-BotEndpoint {
    <#
    .SYNOPSIS
        Gets the bot's messaging endpoint URL.
    
    .EXAMPLE
        Get-BotEndpoint
    #>
    
    $fqdn = az containerapp show `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --query "properties.configuration.ingress.fqdn" -o tsv

    if ($fqdn) {
        $endpoint = "https://$fqdn/api/messages"
        Write-Host "`nBot Messaging Endpoint:" -ForegroundColor Cyan
        Write-Host $endpoint -ForegroundColor Green
        
        # Copy to clipboard
        $endpoint | Set-Clipboard
        Write-Info "Endpoint copied to clipboard!"
        
        return $endpoint
    }
    else {
        Write-Error "Could not retrieve bot endpoint"
    }
}

function New-TeamsPackage {
    <#
    .SYNOPSIS
        Creates a Teams app package using the Create-TeamsPackage.ps1 script.
    
    .DESCRIPTION
        Wrapper function that calls the Create-TeamsPackage.ps1 script
        to generate a Teams app manifest package.
    
    .EXAMPLE
        New-TeamsPackage
    #>
    
    Write-Step "Creating Teams App Package"
    
    $packageScript = Join-Path $PSScriptRoot "Create-TeamsPackage.ps1"
    
    if (Test-Path $packageScript) {
        & $packageScript
    } else {
        Write-Error "Create-TeamsPackage.ps1 not found at: $packageScript"
    }
}

function Deploy-Complete {
    <#
    .SYNOPSIS
        Performs a complete deployment: build, deploy, and create Teams package.
    
    .PARAMETER ImageTag
        The tag for the Docker image.
    
    .EXAMPLE
        Deploy-Complete -ImageTag "v1"
    #>
    param(
        [string]$ImageTag = "v$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    )
    
    Write-Host "`n" -NoNewline
    Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  COMPLETE DEPLOYMENT                                          ║" -ForegroundColor Cyan
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Image Tag: $ImageTag" -ForegroundColor Cyan
    Write-Host "║  RSC Enabled: $($script:ENABLE_RSC)" -ForegroundColor Cyan
    Write-Host "║  AI Enabled: $($script:ENABLE_AI)" -ForegroundColor Cyan
    Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    # Step 1: Redeploy code
    Redeploy-BotCode -ImageTag $ImageTag
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Deployment failed. Aborting."
        return
    }
    
    # Step 2: Create Teams package
    Write-Host "`n"
    New-TeamsPackage
    
    # Step 3: Show summary
    Write-Host "`n"
    Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║  COMPLETE DEPLOYMENT FINISHED!                                ║" -ForegroundColor Green
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Green
    Write-Host "║  Next Steps:                                                  ║" -ForegroundColor Green
    Write-Host "║  1. Upload Teams package to Teams Admin Center                ║" -ForegroundColor Green
    Write-Host "║  2. Install the app to your team/users                        ║" -ForegroundColor Green
    Write-Host "║  3. Test the bot with /help command                           ║" -ForegroundColor Green
    Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
}

function Show-Config {
    <#
    .SYNOPSIS
        Displays current configuration loaded from .env file.
    #>
    
    Write-Host "`n" -NoNewline
    Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║  CURRENT CONFIGURATION                                        ║" -ForegroundColor Cyan
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Source: $($script:ENV_FILE)" -ForegroundColor Cyan
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Azure Resources:" -ForegroundColor Yellow
    Write-Host "║    Resource Group:    $($script:RESOURCE_GROUP)" -ForegroundColor White
    Write-Host "║    Location:          $($script:LOCATION)" -ForegroundColor White
    Write-Host "║    ACR:               $($script:ACR_NAME)" -ForegroundColor White
    Write-Host "║    Container App:     $($script:CONTAINER_APP_NAME)" -ForegroundColor White
    Write-Host "║    UAMI:              $($script:UAMI_NAME)" -ForegroundColor White
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Bot Configuration:" -ForegroundColor Yellow
    Write-Host "║    Bot Name:          $($script:BOT_NAME)" -ForegroundColor White
    Write-Host "║    Bot App ID:        $($script:BOT_APP_ID)" -ForegroundColor White
    Write-Host "╠═══════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  Feature Flags:" -ForegroundColor Yellow
    Write-Host "║    RSC Enabled:       $($script:ENABLE_RSC)" -ForegroundColor $(if ($script:ENABLE_RSC) { "Green" } else { "Gray" })
    Write-Host "║    AI Enabled:        $($script:ENABLE_AI)" -ForegroundColor $(if ($script:ENABLE_AI) { "Green" } else { "Gray" })
    Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
}

# =============================================================================
# QUICK REFERENCE
# =============================================================================

function Show-Help {
    <#
    .SYNOPSIS
        Displays available functions and usage examples.
    #>
    
    Write-Host @"

╔═══════════════════════════════════════════════════════════════════════════════╗
║                    CROSS-TENANT BOT DEPLOYMENT SCRIPT                         ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  Configuration is loaded from: .env file in project root                     ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  QUICK START:                                                                 ║
║  ────────────                                                                 ║
║    Deploy-Complete [-ImageTag "v1"]                                           ║
║        Full deployment + Teams package creation (recommended)                 ║
║                                                                               ║
║    Show-Config                                                                ║
║        Display current configuration from .env file                           ║
║                                                                               ║
║  DEPLOYMENT FUNCTIONS:                                                        ║
║  ─────────────────────                                                        ║
║    Deploy-BotInfrastructure [-ImageTag "v1"]                                  ║
║        Full deployment: ACR, Container Apps Environment, Container App        ║
║                                                                               ║
║    Redeploy-BotCode [-ImageTag "v2"]                                          ║
║        Rebuild image and update Container App (most common operation)         ║
║                                                                               ║
║    Update-BotEnvironmentVariables [-EnvFile "env.prod"]                       ║
║        Update env vars without rebuilding image                               ║
║                                                                               ║
║  TEAMS PACKAGE:                                                               ║
║  ──────────────                                                               ║
║    New-TeamsPackage                                                           ║
║        Create Teams app package (uses ENABLE_RSC flag for template)           ║
║                                                                               ║
║  VERIFICATION FUNCTIONS:                                                      ║
║  ───────────────────────                                                      ║
║    Verify-BotDeployment                                                       ║
║        Check all bot configurations and display details                       ║
║                                                                               ║
║    Get-BotEndpoint                                                            ║
║        Get the bot's messaging endpoint URL                                   ║
║                                                                               ║
║    Get-BotLogs [-Follow] [-Tail 100]                                          ║
║        View Container App logs                                                ║
║                                                                               ║
║  FEATURE FLAGS (from .env):                                                   ║
║  ──────────────────────────                                                   ║
║    ENABLE_RSC=$($script:ENABLE_RSC.ToString().ToLower())    - Channel message access via Graph API                  ║
║    ENABLE_AI=$($script:ENABLE_AI.ToString().ToLower())     - AI-powered responses                               ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan
}

# Show help on script load
Write-Host "`nBot Deployment Script Loaded. Type 'Show-Help' for available commands." -ForegroundColor Green
Write-Host "Configuration loaded from: $($script:ENV_FILE)" -ForegroundColor Gray
Write-Host "RSC: $($script:ENABLE_RSC) | AI: $($script:ENABLE_AI)" -ForegroundColor Gray
