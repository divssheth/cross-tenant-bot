# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
AI Prompts and Instructions

Customize these prompts to change how the AI agent behaves.
These are used by the default SimpleAgent implementation.
"""

import os

# ============================================================================
# System Instructions for the AI Agent
# ============================================================================

DEFAULT_AGENT_INSTRUCTIONS = """You are a helpful Teams assistant that has access to channel conversation history.

Your capabilities:
- Answer questions based on the conversation context provided
- Summarize discussions from channel history
- Help users find information from past conversations
- Provide helpful responses in a professional, friendly tone

Guidelines:
- Use the conversation context to provide relevant answers
- If the context doesn't contain the answer, say so politely
- Keep responses concise and actionable
- Format responses using Markdown for Teams (bold, lists, etc.)
- Always be helpful and professional

When referencing messages from context, mention who said what and approximately when."""

# Load from environment or use default
AGENT_INSTRUCTIONS = os.getenv("AI_AGENT_INSTRUCTIONS", DEFAULT_AGENT_INSTRUCTIONS)


# ============================================================================
# Prompt Templates
# ============================================================================

QUESTION_ANSWER_PROMPT = """Based on the following conversation history, answer this question: {question}

Conversation History:
{context}

If the answer cannot be found in the conversation history, say so clearly.
If you find relevant information, cite who said it."""


SUMMARIZE_PROMPT = """Please summarize the following conversation{focus}:

{context}

Provide a concise summary highlighting:
1. Main topics discussed
2. Key decisions or action items
3. Any unresolved questions"""


CHAT_PROMPT = """Conversation Type: {conversation_type}

Recent Conversation History:
{context}

{additional_context}

User's Message: {user_message}

Please provide a helpful response based on the conversation context."""


# ============================================================================
# Response Templates
# ============================================================================

AI_UNAVAILABLE_MESSAGE = """I received your message: **{message}**

⚠️ AI features are currently not available. Please check:
- AZURE_AI_PROJECT_ENDPOINT is configured
- The bot has access to Azure AI Foundry
- You have run `az login` for local testing

You can still use commands like `/help`, `/context`, and `/info`."""


RSC_DISABLED_MESSAGE = """**📚 Channel Context:**

⚠️ RSC is disabled in this deployment.

Channel message history requires RSC permissions. Currently using in-memory context only.

To enable RSC:
1. Set `ENABLE_RSC=true` in environment variables
2. Configure Graph API credentials
3. Use a manifest with RSC permissions"""
