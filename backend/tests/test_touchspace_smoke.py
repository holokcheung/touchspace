"""Opt-in, tiny real OpenRouter Messages tests. Never prints credentials or prompts."""
import asyncio
import os

import pytest

from app.touchspace.chat import MessagesProvider, ProviderConfig, TOOLS, TOOL_ARGS

pytestmark = pytest.mark.skipif(os.environ.get("TOUCHSPACE_RUN_LLM_SMOKE") != "1",reason="Set TOUCHSPACE_RUN_LLM_SMOKE=1 to spend a small API budget")


def test_real_messages_text():
    async def run():
        config=ProviderConfig.from_env()
        assert config.api_key, "Configure backend/.env"
        response=await MessagesProvider(config).send("Be brief.",[{"role":"user","content":[{"type":"text","text":"Say hello in one sentence."}]}],[])
        assert any(b.get("type")=="text" and b.get("text") for b in response["content"])
    asyncio.run(run())


def test_real_messages_typed_tool_and_result():
    async def run():
        config=ProviderConfig.from_env()
        assert config.api_key
        provider=MessagesProvider(config)
        messages=[{"role":"user","content":[{"type":"text","text":"Describe this map. Call overview first."}]}]
        response=await provider.send("Use the overview tool.",messages,TOOLS,{"type":"tool","name":"overview"})
        call=next(b for b in response["content"] if b.get("type")=="tool_use")
        assert call["name"]=="overview"
        assert TOOL_ARGS["overview"].model_validate(call["input"]).offset == 0
        messages += [{"role":"assistant","content":response["content"]},
                     {"role":"user","content":[{"type":"tool_result","tool_use_id":call["id"],"content":'{"coverage":"partial","rooms":[{"id":"lobby","name":"Lobby"}],"destinations":[]}'}]}]
        final=await provider.send("Briefly summarize the verified tool output. No more tools needed.",messages,TOOLS)
        assert any(b.get("type")=="text" and "lobby" in b.get("text","").lower() for b in final["content"])
    asyncio.run(run())
