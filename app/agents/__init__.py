# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""
Agents Module - AI Agent Implementations

This module contains AI agent implementations that can be customized or replaced.

To use a different agent:
1. Create a new class that extends BaseAgent
2. Implement the required methods
3. Update get_agent() to return your implementation

Example:
    # agents/my_agent.py
    from agents.base import BaseAgent
    
    class MyAgent(BaseAgent):
        async def process(self, user_message, context, history):
            # Your custom logic here
            return "Response"
    
    # agents/__init__.py
    def get_agent():
        from agents.my_agent import MyAgent
        return MyAgent()
"""

from typing import Optional

from app.agents.base import BaseAgent
from app.agents.simple_agent import SimpleAgent

# Agent singleton
_agent_instance: Optional[BaseAgent] = None


def get_agent() -> BaseAgent:
    """
    Factory function to get the configured agent.
    
    Modify this function to return your custom agent implementation.
    
    Returns:
        An instance of BaseAgent (or a subclass)
    
    Examples:
        # Default: Use SimpleAgent (Microsoft Agent Framework)
        return SimpleAgent()
        
        # Use LangGraph
        from agents.langgraph_agent import LangGraphAgent
        return LangGraphAgent()
        
        # Use Semantic Kernel
        from agents.sk_agent import SemanticKernelAgent
        return SemanticKernelAgent()
        
        # Use config-driven selection
        if settings.AGENT_TYPE == "langgraph":
            return LangGraphAgent()
        return SimpleAgent()
    """
    global _agent_instance
    
    if _agent_instance is None:
        # Default: Use SimpleAgent with Microsoft Agent Framework
        _agent_instance = SimpleAgent()
    
    return _agent_instance


async def cleanup_agent():
    """Clean up agent resources."""
    global _agent_instance
    
    if _agent_instance is not None:
        await _agent_instance.cleanup()
    _agent_instance = None


__all__ = ["BaseAgent", "SimpleAgent", "get_agent", "cleanup_agent"]
