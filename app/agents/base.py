# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Base Agent - Abstract interface for AI agents.

Extend this class to implement your own AI orchestration using any framework:
- Microsoft Agent Framework (default)
- LangGraph
- Semantic Kernel
- OpenAI directly
- Any other framework

The interface is simple: string in, string out.
What happens inside your implementation is up to you.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base class for AI agents.
    
    Implement this interface to create your own agent using any AI framework.
    The bot infrastructure will call these methods to get AI-powered responses.
    
    Example implementation:
        class MyAgent(BaseAgent):
            def __init__(self):
                # Initialize your framework (LangGraph, SK, etc.)
                self.client = ...
            
            async def process(self, user_message, context, history):
                # Your AI logic here
                response = await self.client.chat(...)
                return response
            
            async def summarize(self, messages):
                # Your summarization logic
                return await self.client.summarize(...)
            
            async def answer_question(self, question, messages):
                # Your Q&A logic
                return await self.client.answer(...)
    """
    
    @property
    def is_available(self) -> bool:
        """
        Check if the agent is available and configured.
        
        Override this to add your own availability checks.
        
        Returns:
            True if the agent can process requests
        """
        return True
    
    @abstractmethod
    async def process(
        self,
        user_message: str,
        context: str,
        history: List[Dict[str, Any]],
        conversation_type: str = "personal"
    ) -> str:
        """
        Process a user message and generate a response.
        
        This is the main method for handling user interactions.
        Implement your AI logic here.
        
        Args:
            user_message: The user's input message
            context: Formatted conversation context string
            history: List of message dictionaries from conversation
            conversation_type: "personal", "groupChat", or "channel"
            
        Returns:
            The agent's response string
        """
        pass
    
    @abstractmethod
    async def summarize(
        self,
        messages: List[Dict[str, Any]],
        focus: Optional[str] = None
    ) -> str:
        """
        Generate a summary of the conversation.
        
        Args:
            messages: List of message dictionaries to summarize
            focus: Optional focus area for the summary
            
        Returns:
            Summary string
        """
        pass
    
    @abstractmethod
    async def answer_question(
        self,
        question: str,
        messages: List[Dict[str, Any]]
    ) -> str:
        """
        Answer a specific question based on conversation context.
        
        Args:
            question: The user's question
            messages: List of message dictionaries for context
            
        Returns:
            Answer string
        """
        pass
    
    async def cleanup(self):
        """
        Clean up agent resources.
        
        Override this if your agent needs cleanup (e.g., closing connections).
        """
        pass
    
    def _format_messages_for_context(
        self,
        messages: List[Dict[str, Any]],
        max_messages: int = 20
    ) -> str:
        """
        Helper: Format message list into a context string.
        
        You can use this in your implementation or create your own formatting.
        
        Args:
            messages: List of message dictionaries
            max_messages: Maximum messages to include
            
        Returns:
            Formatted context string
        """
        import re
        
        if not messages:
            return "No conversation history available."
        
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        
        formatted_lines = []
        for msg in recent_messages:
            sender = msg.get("sender_name") or msg.get("from", {}).get("user", {}).get("displayName", "Unknown")
            text = msg.get("text") or msg.get("body", {}).get("content", "")
            timestamp = msg.get("timestamp") or msg.get("createdDateTime", "")
            
            # Clean up HTML content
            if "<" in text and ">" in text:
                text = re.sub(r'<[^>]+>', '', text)
            
            if text.strip():
                formatted_lines.append(f"[{timestamp}] {sender}: {text}")
        
        return "\n".join(formatted_lines) if formatted_lines else "No messages with content found."
