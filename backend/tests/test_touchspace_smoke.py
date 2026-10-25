"""Opt-in, tiny real Claude API tests. Never prints credentials or prompts."""
import asyncio
import os

import pytest

from app.touchspace.chat import MessagesProvider, ProviderConfig, TOOLS, TOOL_ARGS

pytestmark = pytest.mark.skipif(os.environ.get("TOUCHSPACE_RUN_LLM_SMOKE") != "1",reason="Set TOUCHSPACE_RUN_LLM_SMOKE=1 to spend a small API budget")


def test_real_messages_text():
    async def run():
        config=ProviderConfig.from_env()
        assert config.api_key, "Set ANTHROPIC_API_KEY in backend/.env"
        response=await MessagesProvider(config).send("Be brief.",[{"role":"user","content":[{"type":"text","text":"Say hello in one sentence."}]}],[])
        assert any(b.get("type")=="text" and b.get("text") for b in response["content"])
    asyncio.run(run())


def test_real_messages_typed_tool_and_result():
    async def run():
        config=ProviderConfig.from_env()
        assert config.api_key
        provider=MessagesProvider(config)
        # Forced tool_choice is a 400 on Claude Opus 5.5, so the prompt asks for the tool instead. The
        # system prompt stays identical across the loop so the replayed thinking blocks remain valid.
        system="Call the overview tool once, then summarize its verified result in one sentence."
        messages=[{"role":"user","content":[{"type":"text","text":"Describe this map. Call overview first."}]}]
        response=await provider.send(system,messages,TOOLS)
        call=next(b for b in response["content"] if b.get("type")=="tool_use")
        assert call["name"]=="overview"
        assert TOOL_ARGS["overview"].model_validate(call["input"]).offset == 0
        # The assistant turn goes back unchanged, thinking blocks included.
        messages += [{"role":"assistant","content":response["content"]},
                     {"role":"user","content":[{"type":"tool_result","tool_use_id":call["id"],"content":'{"coverage":"partial","rooms":[{"id":"lobby","name":"Lobby"}],"destinations":[]}'}]}]
        final=await provider.send(system,messages,TOOLS)
        assert any(b.get("type")=="text" and "lobby" in b.get("text","").lower() for b in final["content"])
    asyncio.run(run())
