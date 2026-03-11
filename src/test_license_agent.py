"""Quick test for license agent creation."""
import os, sys, inspect, asyncio
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('../.env', override=True)

from app.agents.license_agent import create_license_agent, query_license_knowledge_base
from agent_framework.azure import AzureOpenAIResponsesClient
from azure.identity import AzureCliCredential

cred = AzureCliCredential()
client = AzureOpenAIResponsesClient(
    credential=cred,
    endpoint=os.getenv('FOUNDRY_PROJECT_ENDPOINT'),
    deployment_name='gpt-4o',
)
agent = create_license_agent(client, cred)
if agent:
    print(f"OK: license_agent created, name={agent.name}")
else:
    print("FAIL: license_agent is None")

print(f"Tool is async: {inspect.iscoroutinefunction(query_license_knowledge_base.func)}")

# Quick async invocation test
async def test_tool():
    result = await query_license_knowledge_base.invoke(arguments=None, question="What is Microsoft 365 E5?")
    print(f"Tool result (first 200 chars): {str(result)[:200]}")

asyncio.run(test_tool())
