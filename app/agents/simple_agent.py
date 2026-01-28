# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Simple Agent - Default implementation using Microsoft Agent Framework.

This is the default agent implementation that uses Azure AI Foundry
with the Microsoft Agent Framework (AzureAIProjectAgentProvider).

To replace this agent:
1. Create a new class extending BaseAgent
2. Update agents/__init__.py to return your implementation

This implementation can be used as a reference for creating your own agent.
"""

import os
import logging
from typing import List, Dict, Any, Optional

from app.agents.base import BaseAgent
from app.config.settings import settings
from app.config.prompts import (
    AGENT_INSTRUCTIONS,
    QUESTION_ANSWER_PROMPT,
    SUMMARIZE_PROMPT,
    CHAT_PROMPT,
    AI_UNAVAILABLE_MESSAGE,
)

logger = logging.getLogger(__name__)


class SimpleAgent(BaseAgent):
    """
    Default agent implementation using Microsoft Agent Framework.
    
    Uses AzureAIProjectAgentProvider for agent creation and management.
    Supports UAMI (User-Assigned Managed Identity) for Azure and 
    AzureCliCredential for local testing.
    
    Configuration (from settings):
        - AZURE_AI_PROJECT_ENDPOINT: Azure AI Foundry endpoint
        - AZURE_AI_MODEL_DEPLOYMENT: Model deployment name (default: gpt-4o)
        - AI_AGENT_INSTRUCTIONS: System instructions for the agent
    """
    
    def __init__(self):
        """Initialize the Simple Agent."""
        self._provider = None
        self._credential = None
        self._agent = None
        self._initialized = False
        
        # Get configuration from settings
        self._endpoint = settings.AZURE_AI_PROJECT_ENDPOINT
        self._deployment = settings.AZURE_AI_MODEL_DEPLOYMENT
        self._instructions = AGENT_INSTRUCTIONS
        
        logger.info(f"SimpleAgent Config - Endpoint: {self._endpoint[:30] + '...' if self._endpoint else 'Not set'}")
        logger.info(f"SimpleAgent Config - Deployment: {self._deployment}")
        
        if not self._endpoint:
            logger.warning("SimpleAgent disabled - AZURE_AI_PROJECT_ENDPOINT not configured")
    
    @property
    def is_available(self) -> bool:
        """Check if the agent is configured and available."""
        return bool(self._endpoint) and settings.ENABLE_AI
    
    async def _ensure_initialized(self) -> bool:
        """Initialize the agent provider and create agent on first use."""
        if self._initialized and self._agent is not None:
            return True
        
        if not self.is_available:
            return False
            
        try:
            from agent_framework.azure import AzureAIProjectAgentProvider
            from azure.identity.aio import DefaultAzureCredential, AzureCliCredential
            
            # Get UAMI client ID for managed identity
            uami_client_id = settings.AZURE_CLIENT_ID
            
            # Check if running locally
            local_debug = settings.LOCAL_DEBUG
            
            if local_debug:
                # For local testing, use AzureCliCredential (run `az login` first)
                logger.info("🔧 LOCAL_DEBUG=true - Using AzureCliCredential for local testing")
                self._credential = AzureCliCredential()
            else:
                # In Azure, use DefaultAzureCredential with UAMI
                logger.info(f"🔧 Using DefaultAzureCredential with UAMI: {uami_client_id}")
                self._credential = DefaultAzureCredential(
                    managed_identity_client_id=uami_client_id
                )
            
            # Set environment variables for the provider (it reads from env)
            os.environ["AZURE_AI_PROJECT_ENDPOINT"] = self._endpoint
            os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"] = self._deployment
            
            # Create the provider with just the credential (reads endpoint from env)
            self._provider = AzureAIProjectAgentProvider(
                credential=self._credential
            )
            
            # Enter the async context
            await self._credential.__aenter__()
            await self._provider.__aenter__()
            
            # Create the agent
            self._agent = await self._provider.create_agent(
                name="TeamsAssistant",
                instructions=self._instructions,
            )
            
            logger.info(f"✅ SimpleAgent created: {self._agent.name}")
            self._initialized = True
            return True
            
        except ImportError as e:
            logger.error(f"❌ Required package not installed: {e}")
            logger.error("Run: pip install agent-framework[azure]")
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize SimpleAgent: {e}", exc_info=True)
            self._initialized = False
            return False
    
    async def process(
        self,
        user_message: str,
        context: str,
        history: List[Dict[str, Any]],
        conversation_type: str = "personal"
    ) -> str:
        """
        Process a user message and generate an AI response.
        
        Args:
            user_message: The user's input message
            context: Formatted conversation context string
            history: List of message dictionaries
            conversation_type: Type of conversation
            
        Returns:
            AI-generated response string
        """
        if not self.is_available:
            return AI_UNAVAILABLE_MESSAGE.format(message=user_message)
        
        if not await self._ensure_initialized():
            return AI_UNAVAILABLE_MESSAGE.format(message=user_message)
        
        try:
            # Format context if not already formatted
            if not context:
                context = self._format_messages_for_context(history)
            
            # Build the prompt
            prompt = CHAT_PROMPT.format(
                conversation_type=conversation_type,
                context=context,
                additional_context="",
                user_message=user_message
            )
            
            # Use the agent to generate a response
            result = await self._agent.run(prompt)
            
            ai_response = str(result) if result else None
            
            if not ai_response:
                return "I processed your request but couldn't generate a response. Please try again."
            
            logger.info(f"SimpleAgent response generated ({len(ai_response)} chars)")
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating AI response: {e}", exc_info=True)
            return f"I encountered an error processing your request.\n\n_Error: {str(e)}_"
    
    async def summarize(
        self,
        messages: List[Dict[str, Any]],
        focus: Optional[str] = None
    ) -> str:
        """Generate a summary of the conversation."""
        if not self.is_available or not await self._ensure_initialized():
            return "AI summarization is not available."
        
        try:
            context_text = self._format_messages_for_context(messages, max_messages=50)
            focus_text = f" with focus on: {focus}" if focus else ""
            
            prompt = SUMMARIZE_PROMPT.format(
                focus=focus_text,
                context=context_text
            )
            
            result = await self._agent.run(prompt)
            return str(result) if result else "Could not generate summary."
            
        except Exception as e:
            logger.error(f"Error summarizing conversation: {e}", exc_info=True)
            return f"Could not generate summary: {str(e)}"
    
    async def answer_question(
        self,
        question: str,
        messages: List[Dict[str, Any]]
    ) -> str:
        """Answer a specific question based on conversation context."""
        if not self.is_available or not await self._ensure_initialized():
            return "AI question answering is not available."
        
        try:
            context_text = self._format_messages_for_context(messages, max_messages=30)
            
            prompt = QUESTION_ANSWER_PROMPT.format(
                question=question,
                context=context_text
            )
            
            result = await self._agent.run(prompt)
            return str(result) if result else "Could not answer question."
            
        except Exception as e:
            logger.error(f"Error answering question: {e}", exc_info=True)
            return f"Could not answer question: {str(e)}"
    
    async def cleanup(self):
        """Clean up agent resources."""
        try:
            if self._provider:
                await self._provider.__aexit__(None, None, None)
            if self._credential:
                await self._credential.__aexit__(None, None, None)
        except Exception as e:
            logger.warning(f"Error during SimpleAgent cleanup: {e}")
        finally:
            self._agent = None
            self._provider = None
            self._credential = None
            self._initialized = False
