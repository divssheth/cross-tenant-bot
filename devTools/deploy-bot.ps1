<#
.SYNOPSIS
    Deploys and manages a Cross-Tenant Teams Bot with User Assigned Managed Identity (UAMI) on Azure Container Apps.

.DESCRIPTION
    This script provides functions to:
    - Deploy the complete infrastructure (ACR, Container Apps Environment, Container App)
    - Redeploy/update the bot code to the existing Container App
    - Verify the deployment and configuration
    - Troubleshoot common issues

    The bot uses UAMI for authentication which eliminates the need for client secrets.

.NOTES
    Author: Divyesh
    Bot Name: tescobotappdivye
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
    # Verify deployment
    .\deploy-bot.ps1
    Verify-BotDeployment
#>

# =============================================================================
# CONFIGURATION VARIABLES
# =============================================================================

# Resource Group & Location
$script:RESOURCE_GROUP = "tesco-bot-rg"
$script:LOCATION = "eastus"

# Azure Container Registry
$script:ACR_NAME = "crosstenantbotacr"  # Must be globally unique, lowercase

# Container Apps
$script:CONTAINER_ENV_NAME = "crosstenant-bot-env"
$script:CONTAINER_APP_NAME = "crosstenant-bot-app"

# User Assigned Managed Identity
$script:UAMI_NAME = "tescobot"

# Bot Configuration
$script:BOT_NAME = "tescobotdivnp"
$script:BOT_APP_ID = "631cc7ce-2a7b-4d31-9ae0-3a5faa984d73"

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
        --env-vars `
            "AZURE_CLIENT_ID=$($uami.ClientId)" `
            "AZURE_TENANT_ID=$tenantId" `
            "MICROSOFT_APP_ID=$script:BOT_APP_ID" `
            "CONTAINER_APP_NAME=$script:CONTAINER_APP_NAME"
    
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
║  CONFIGURATION:                                                               ║
║  ──────────────                                                               ║
║    Resource Group:    $script:RESOURCE_GROUP                                          ║
║    Container App:     $script:CONTAINER_APP_NAME                                  ║
║    ACR:               $script:ACR_NAME                                      ║
║    UAMI:              $script:UAMI_NAME                                               ║
║    Bot App ID:        $script:BOT_APP_ID                          ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan
}

# Show help on script load
Write-Host "`nBot Deployment Script Loaded. Type 'Show-Help' for available commands." -ForegroundColor Green
