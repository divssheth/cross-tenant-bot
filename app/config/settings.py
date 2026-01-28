# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Settings - Centralized Configuration

All environment variables and configuration values are centralized here.
Modify this file to add new configuration options.
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """
    Centralized settings for the Cross-Tenant Teams Bot.
    
    All values are loaded from environment variables.
    Override these values in your .env file or Azure configuration.
    """
    
    # =========================================================================
    # Azure Identity (Required)
    # =========================================================================
    
    # User-Assigned Managed Identity Client ID
    AZURE_CLIENT_ID: str = field(default_factory=lambda: os.getenv("AZURE_CLIENT_ID", ""))
    
    # Azure Tenant ID
    AZURE_TENANT_ID: str = field(default_factory=lambda: os.getenv("AZURE_TENANT_ID", ""))
    
    # Microsoft App ID for Bot Framework (same as AZURE_CLIENT_ID for UAMI bots)
    MICROSOFT_APP_ID: str = field(default_factory=lambda: os.getenv("MICROSOFT_APP_ID", ""))
    
    # Bot app type (SingleTenant for UAMI)
    MICROSOFT_APP_TYPE: str = field(default_factory=lambda: os.getenv("MICROSOFT_APP_TYPE", "SingleTenant"))
    
    # =========================================================================
    # Feature Flags
    # =========================================================================
    
    # Enable RSC (Resource-Specific Consent) for channel message access
    ENABLE_RSC: bool = field(
        default_factory=lambda: os.getenv("ENABLE_RSC", "false").lower() == "true"
    )
    
    # Enable AI features
    ENABLE_AI: bool = field(
        default_factory=lambda: os.getenv("ENABLE_AI", "true").lower() == "true"
    )
    
    # Local debug mode (uses client_secret instead of UAMI)
    LOCAL_DEBUG: bool = field(
        default_factory=lambda: os.getenv("LOCAL_DEBUG", "false").lower() == "true"
    )
    
    # =========================================================================
    # AI Configuration
    # =========================================================================
    
    # Azure AI Foundry/Project endpoint
    AZURE_AI_PROJECT_ENDPOINT: str = field(
        default_factory=lambda: os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    )
    
    # Model deployment name
    AZURE_AI_MODEL_DEPLOYMENT: str = field(
        default_factory=lambda: os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o")
    )
    
    # =========================================================================
    # RSC/Graph Configuration
    # =========================================================================
    
    # Graph App ID (multi-tenant app registration for RSC)
    GRAPH_APP_ID: str = field(default_factory=lambda: os.getenv("GRAPH_APP_ID", ""))
    
    # Azure Key Vault name (for retrieving Graph client secret)
    KEY_VAULT_NAME: str = field(default_factory=lambda: os.getenv("KEY_VAULT_NAME", ""))
    
    # Secret name in Key Vault for Graph client secret
    GRAPH_CLIENT_SECRET_NAME: str = field(
        default_factory=lambda: os.getenv("GRAPH_CLIENT_SECRET_NAME", "graph-client-secret")
    )
    
    # Direct client secret (for local dev only - not recommended for production)
    GRAPH_CLIENT_SECRET: str = field(
        default_factory=lambda: os.getenv("GRAPH_CLIENT_SECRET", "")
    )
    
    # =========================================================================
    # Conversation Settings
    # =========================================================================
    
    # Maximum messages to store per conversation in memory
    MAX_CONTEXT_MESSAGES: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONTEXT_MESSAGES", "20"))
    )
    
    # Maximum messages to fetch from Graph API
    MAX_GRAPH_MESSAGES: int = field(
        default_factory=lambda: int(os.getenv("MAX_GRAPH_MESSAGES", "20"))
    )
    
    # =========================================================================
    # Server Settings
    # =========================================================================
    
    # Messaging endpoint URL
    MESSAGING_ENDPOINT: str = field(
        default_factory=lambda: os.getenv("MESSAGING_ENDPOINT", "https://localhost:8080/api/messages")
    )
    
    # Server port
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "3978")))
    
    # =========================================================================
    # Local Testing (only used when LOCAL_DEBUG=true)
    # =========================================================================
    
    LOCAL_TEST_APP_ID: str = field(
        default_factory=lambda: os.getenv("LOCAL_TEST_APP_ID", "")
    )
    
    LOCAL_TEST_APP_SECRET: str = field(
        default_factory=lambda: os.getenv("LOCAL_TEST_APP_SECRET", "")
    )
    
    def __post_init__(self):
        """Validate required settings after initialization."""
        self._validate()
    
    def _validate(self):
        """Validate required configuration."""
        missing = []
        
        if not self.AZURE_CLIENT_ID:
            missing.append("AZURE_CLIENT_ID")
        if not self.AZURE_TENANT_ID:
            missing.append("AZURE_TENANT_ID")
        if not self.MICROSOFT_APP_ID:
            missing.append("MICROSOFT_APP_ID")
        
        if missing:
            logger.warning(f"Missing environment variables: {', '.join(missing)}")
            logger.warning("Some features may not work correctly.")
    
    @property
    def is_ai_available(self) -> bool:
        """Check if AI is configured and enabled."""
        return self.ENABLE_AI and bool(self.AZURE_AI_PROJECT_ENDPOINT)
    
    @property
    def is_rsc_available(self) -> bool:
        """Check if RSC is configured and enabled."""
        return self.ENABLE_RSC and bool(self.GRAPH_APP_ID)
    
    @property
    def bot_app_id(self) -> str:
        """Get the bot application ID (UAMI Client ID)."""
        return self.AZURE_CLIENT_ID or self.MICROSOFT_APP_ID
    
    def log_config(self):
        """Log configuration for debugging (excluding sensitive data)."""
        logger.info("=== Bot Configuration ===")
        logger.info(f"AZURE_CLIENT_ID: {self.AZURE_CLIENT_ID[:8]}..." if self.AZURE_CLIENT_ID else "AZURE_CLIENT_ID: Not set")
        logger.info(f"AZURE_TENANT_ID: {self.AZURE_TENANT_ID[:8]}..." if self.AZURE_TENANT_ID else "AZURE_TENANT_ID: Not set")
        logger.info(f"ENABLE_RSC: {self.ENABLE_RSC}")
        logger.info(f"ENABLE_AI: {self.ENABLE_AI}")
        logger.info(f"AI Endpoint: {self.AZURE_AI_PROJECT_ENDPOINT[:30]}..." if self.AZURE_AI_PROJECT_ENDPOINT else "AI Endpoint: Not set")
        logger.info(f"LOCAL_DEBUG: {self.LOCAL_DEBUG}")
        logger.info("========================")


# Global settings instance - use this throughout the application
settings = Settings()
