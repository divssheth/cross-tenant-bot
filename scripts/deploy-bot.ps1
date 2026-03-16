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
        3. Optionally sync environment variables from .env file
    
    .PARAMETER ImageTag
        The tag for the new Docker image. Defaults to timestamp-based tag.
    
    .PARAMETER SyncEnv
        If specified, syncs environment variables from .env file after deploying.
    
    .EXAMPLE
        Redeploy-BotCode
        # Uses auto-generated tag like "v20260121-143052"
    
    .EXAMPLE
        Redeploy-BotCode -ImageTag "v3"
        # Uses specific tag "v3"
    
    .EXAMPLE
        Redeploy-BotCode -SyncEnv
        # Deploy code AND sync all .env variables to ACA
    #>
    param(
        [string]$ImageTag = "v$(Get-Date -Format 'yyyyMMdd-HHmmss')",
        [switch]$SyncEnv
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
        
        # Sync environment variables if requested
        if ($SyncEnv) {
            Write-Step "Step 3: Syncing Environment Variables"
            Update-BotEnvironmentVariables -EnvFile ".env"
        }
        
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
        if ($SyncEnv) {
        Write-Host "║  Environment: Synced from .env                                ║" -ForegroundColor Green
        }
        Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
    }
    else {
        Write-Error "Failed to update Container App"
    }
}

function Update-BotEnvironmentVariables {
    <#
    .SYNOPSIS
        Updates the environment variables on the Container App from the .env file.
    
    .DESCRIPTION
        Reads all environment variables from the .env file and sets them on the Container App.
        Skips comments and empty lines. Handles values with special characters.
    
    .PARAMETER EnvFile
        Path to the environment file. Defaults to ".env".

    .PARAMETER ExcludeSecrets
        If specified, excludes variables that appear to be secrets (containing SECRET, PASSWORD, KEY).
    
    .EXAMPLE
        Update-BotEnvironmentVariables
        # Reads from .env file and updates ACA

    .EXAMPLE
        Update-BotEnvironmentVariables -EnvFile "env.prod"
    #>
    param(
        [string]$EnvFile = ".env",
        [switch]$ExcludeSecrets
    )

    Write-Step "Updating Environment Variables from $EnvFile"

    if (-not (Test-Path $EnvFile)) {
        Write-Error "Environment file not found: $EnvFile"
        return
    }

    # Parse env file - collect KEY=VALUE pairs
    $envVars = @()
    $secretPatterns = @("SECRET", "PASSWORD", "KEY", "TOKEN", "CREDENTIAL")
    
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        
        # Skip comments and empty lines
        if (-not $line -or $line.StartsWith("#")) {
            return
        }
        
        # Parse KEY=VALUE
        $equalIndex = $line.IndexOf("=")
        if ($equalIndex -gt 0) {
            $key = $line.Substring(0, $equalIndex).Trim()
            $value = $line.Substring($equalIndex + 1).Trim()
            
            # Skip if excluding secrets and this looks like a secret
            if ($ExcludeSecrets) {
                $isSecret = $false
                foreach ($pattern in $secretPatterns) {
                    if ($key.ToUpper().Contains($pattern)) {
                        $isSecret = $true
                        Write-Info "Skipping secret: $key"
                        break
                    }
                }
                if ($isSecret) { return }
            }
            
            # Skip empty values
            if (-not $value) {
                Write-Info "Skipping empty value: $key"
                return
            }
            
            # Add to collection
            $envVars += "$key=$value"
        }
    }

    if ($envVars.Count -eq 0) {
        Write-Error "No environment variables found in $EnvFile"
        return
    }

    Write-Info "Found $($envVars.Count) environment variables to set"
    
    # Display what will be set (mask sensitive values)
    $envVars | ForEach-Object {
        $parts = $_ -split "=", 2
        $key = $parts[0]
        $value = $parts[1]
        
        # Mask sensitive values
        $displayValue = $value
        foreach ($pattern in $secretPatterns) {
            if ($key.ToUpper().Contains($pattern)) {
                $displayValue = "********"
                break
            }
        }
        # Truncate long values
        if ($displayValue.Length -gt 50) {
            $displayValue = $displayValue.Substring(0, 47) + "..."
        }
        Write-Host "   $key = $displayValue" -ForegroundColor DarkGray
    }

    Write-Info "Applying environment variables to Container App..."
    
    # Always force LOCAL_DEBUG=false and LOCAL_TRACING=false for ACA deployment
    # (UAMI requires cloud environment; tracing should go to App Insights not AI Toolkit)
    $envVars = $envVars | Where-Object { $_ -notmatch "^LOCAL_DEBUG=" -and $_ -notmatch "^LOCAL_TRACING=" }
    $envVars += "LOCAL_DEBUG=false"
    $envVars += "LOCAL_TRACING=false"
    Write-Info "Forcing LOCAL_DEBUG=false and LOCAL_TRACING=false for ACA deployment"
    
    # Use --set-env-vars with all variables
    az containerapp update `
        --name $script:CONTAINER_APP_NAME `
        --resource-group $script:RESOURCE_GROUP `
        --set-env-vars @envVars

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Environment variables updated successfully!"
        Write-Info "Container App will restart with new environment variables."
    }
    else {
        Write-Error "Failed to update environment variables"
        Write-Info "Try running with fewer variables or check the .env file format."
    }
}

function Sync-EnvToACA {
    <#
    .SYNOPSIS
        Quick sync all .env variables to Azure Container App.
    
    .DESCRIPTION
        Convenience function to sync all environment variables from .env to ACA.
        This is the same as Update-BotEnvironmentVariables with default settings.
    
    .EXAMPLE
        Sync-EnvToACA
    #>
    
    Update-BotEnvironmentVariables -EnvFile ".env"
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
# MONITORING
# =============================================================================

function Deploy-Workbook {
    <#
    .SYNOPSIS
        Deploys the Azure Monitor Workbook for bot monitoring.

    .DESCRIPTION
        Deploys the Cross-Tenant Bot Monitor workbook to Azure using the ARM template
        in scripts/workbook-template.json. Automatically resolves the App Insights
        resource ID from the APPLICATIONINSIGHTS_CONNECTION_STRING in .env.

    .EXAMPLE
        Deploy-Workbook
    #>

    Write-Step "Deploying Azure Monitor Workbook"

    # Read connection string from .env
    $envFile = Join-Path $PSScriptRoot ".." ".env"
    if (-not (Test-Path $envFile)) {
        Write-Error ".env file not found at $envFile"
        return
    }

    $connString = (Get-Content $envFile | Where-Object { $_ -match '^APPLICATIONINSIGHTS_CONNECTION_STRING=' }) -replace '^APPLICATIONINSIGHTS_CONNECTION_STRING=', ''
    if ([string]::IsNullOrWhiteSpace($connString)) {
        Write-Error "APPLICATIONINSIGHTS_CONNECTION_STRING not found or empty in .env"
        return
    }

    # Extract InstrumentationKey from connection string
    $iKey = ($connString -split ';' | Where-Object { $_ -match '^InstrumentationKey=' }) -replace '^InstrumentationKey=', ''
    if ([string]::IsNullOrWhiteSpace($iKey)) {
        Write-Error "Could not extract InstrumentationKey from connection string"
        return
    }
    Write-Info "Instrumentation Key: $iKey"

    # Resolve App Insights resource ID (searches all resource groups in the subscription)
    Write-Info "Looking up Application Insights resource by InstrumentationKey..."
    $appInsightsId = az monitor app-insights component show `
        --query "[?instrumentationKey=='$iKey'].id | [0]" -o tsv

    if ([string]::IsNullOrWhiteSpace($appInsightsId)) {
        Write-Error "Could not find Application Insights resource with key $iKey in this subscription"
        return
    }
    Write-Success "Found App Insights: $appInsightsId"

    # Deploy the workbook ARM template
    $templateFile = Join-Path $PSScriptRoot "workbook-template.json"
    if (-not (Test-Path $templateFile)) {
        Write-Error "Workbook template not found at $templateFile"
        return
    }

    Write-Info "Deploying workbook..."
    az deployment group create `
        --resource-group $script:RESOURCE_GROUP `
        --template-file $templateFile `
        --parameters appInsightsResourceId=$appInsightsId `
        --name "workbook-$(Get-Date -Format 'yyyyMMdd-HHmmss')" `
        --query "properties.provisioningState" -o tsv

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Workbook deployed successfully!"
        Write-Info "View it: Azure Portal -> Application Insights -> Workbooks -> Cross-Tenant Bot Monitor"
    }
    else {
        Write-Error "Workbook deployment failed"
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
║    Redeploy-BotCode [-ImageTag "v2"] [-SyncEnv]                               ║
║        Rebuild image and update Container App (most common operation)         ║
║        Add -SyncEnv to also sync environment variables from .env              ║
║                                                                               ║
║  ENVIRONMENT VARIABLES:                                                       ║
║  ──────────────────────                                                       ║
║    Sync-EnvToACA                                                              ║
║        Quick sync all .env variables to Azure Container App                   ║
║                                                                               ║
║    Update-BotEnvironmentVariables [-EnvFile ".env"] [-ExcludeSecrets]         ║
║        Sync env vars from file to ACA (defaults to .env)                      ║
║                                                                               ║
║  MONITORING:                                                                  ║
║  ───────────                                                                  ║
║    Deploy-Workbook                                                            ║
║        Deploy Azure Monitor Workbook (auto-resolves App Insights resource)    ║
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
