"""Portable contract/API/route/provider tests. No physical localization is claimed."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import plistlib
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx2  # the Anthropic SDK's HTTP layer; the SDK rejects clients from the httpx package
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.touchspace import api
from app.touchspace.chat import ChatService, ChatUnavailable, MessagesProvider, ProviderConfig, SpatialTools
from app.touchspace.models import ChatRequest, MapPackage, Point, Pose, SimulatedPose
from app.touchspace.package import PackageError, check_worldmap, validate_package
from app.touchspace.spatial import SpatialEngine, SpatialError
from app.touchspace.storage import Catalog

FIXTURE = json.loads((Path(__file__).resolve().parents[2]/"shared/fixtures/routes.json").read_text())


@pytest.fixture
def package():
    return MapPackage.model_validate(copy.deepcopy(FIXTURE["package"]))


MESSAGES_URL = "https://api.anthropic.com/v1/messages"
# Claude Opus 5.5 always thinks; its thinking blocks must be passed back unchanged in the tool loop.
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-test"}


@pytest.fixture(autouse=True)
def _real_anthropic_endpoint(monkeypatch):
    # Requests are asserted against the real endpoint; an operator's base-URL override must not change that.
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def message(content, stop_reason=None, **extra):
    """A complete Messages API response body, shaped like the real API's."""
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.get("type") == "tool_use" for b in content) else "end_turn"
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}, **extra}


def mock_provider(handler, api_key="mock", **config):
    """The real SDK client over a mock transport: the SDK builds each request and nothing leaves the process."""
    return MessagesProvider(ProviderConfig(api_key, **config), httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def after_tool_results(body):
    content = body["messages"][-1]["content"]
    return isinstance(content, list) and content[0]["type"] == "tool_result"


def service_for(*calls):
    """A typed LLM response, followed by completion. Never interpret keywords in tests."""
    def handler(request):
        body = json.loads(request.content)
        if after_tool_results(body):
            return httpx2.Response(200, json=message([{"type": "text", "text": "Done"}]))
        return httpx2.Response(200, json=message([THINKING] + [
            {"type": "tool_use", "id": f"call-{i}", "name": name, "input": args}
            for i, (name, args) in enumerate(calls)]))
    return ChatService(mock_provider(handler))


def archive_for(package):
    # Structural test double only, deliberately not represented as device-restorable.
    objects = ["$null", {"$class":plistlib.UID(2),"anchors":[plistlib.UID(3)]},
               {"$classname":"ARWorldMap","$classes":["ARWorldMap","NSObject"]},
               {"$class":plistlib.UID(4),"name":plistlib.UID(5),"identifier":plistlib.UID(6)},
               {"$classname":"ARAnchor","$classes":["ARAnchor","NSObject"]},
               f"touchspace-frame:{package.manifest.coordinate_frame_id}", package.manifest.frame_anchor_id.bytes]
    return plistlib.dumps({"$archiver":"NSKeyedArchiver","$version":100000,"$top":{"root":plistlib.UID(1)},"$objects":objects},fmt=plistlib.FMT_BINARY)


def zip_files(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as z:
        for name,raw in files.items():
            z.writestr(name,raw)
    return data.getvalue()


def files_for(package):
    files = {name+".json":getattr(package,name).model_dump_json(by_alias=True).encode() for name in ["geometry","landmarks","navigation"]}
    files["worldmap.archive"] = archive_for(package)
    package.manifest.checksums = {k:hashlib.sha256(v).hexdigest() for k,v in files.items()}
    files["manifest.json"] = package.manifest.model_dump_json(by_alias=True).encode()
    return files


def question(package, message="Describe the map", pose=True):
    return ChatRequest(map_id=package.manifest.id,session_id=uuid4(),message=message,
        pose=Pose(position=Point(x=1,z=2.5),heading=0,coordinate_frame_id=package.manifest.coordinate_frame_id,
                  observed_at=datetime.now(timezone.utc),verified=True) if pose else None)


def test_shared_route_and_collision_geometry(package):
    engine = SpatialEngine(package)
    route = engine.route(Point(**FIXTURE["start"]),FIXTURE["destinationId"])
    assert route["distance"] == pytest.approx(FIXTURE["expectedDistance"],abs=1e-7)
    assert route["waypoints"] == FIXTURE["expectedWaypoints"]
    points = [Point(**p) for p in route["waypoints"]]
    assert all(engine.clear_segment(a,b) for a,b in zip(points,points[1:]))
    assert not engine.clear_segment(Point(x=1,z=2.5),Point(x=7,z=2.5)) # furniture
    assert not engine.walkable(Point(x=4,z=1)) # divider
    assert not engine.walkable(Point(x=-1,z=2)) # unknown
    assert not engine.walkable(Point(x=2,z=1.1)) # inflated object


@pytest.mark.parametrize("state",["unknown","blocked"])
def test_unconfirmed_doors_are_blocked(package,state):
    package.navigation.doors[0].traversability=state
    with pytest.raises(SpatialError,match="No validated route"):
        SpatialEngine(package).route(Point(x=3.3,z=2.5),"desk")


def test_confirmed_edges_cannot_cross_furniture(package):
    from app.touchspace.models import Node,Edge
    package.navigation.nodes=[Node(id="a",position=Point(x=1,z=2.5),room_id="west"),Node(id="b",position=Point(x=3.5,z=2.5),room_id="west")]
    package.navigation.edges=[Edge(source="a",target="b",confirmed=True,clearance=.3)]
    with pytest.raises(SpatialError,match="graph edge"):
        SpatialEngine(package)


def test_pose_heading_and_freshness(package):
    engine = SpatialEngine(package)
    assert engine.bearing(Point(x=1,z=1),0,Point(x=2,z=1))["direction"] == "right"
    assert engine.bearing(Point(x=1,z=1),3.141592653589793,Point(x=2,z=1))["direction"] == "left"
    req=question(package)
    req.pose.observed_at -= timedelta(seconds=4)
    with pytest.raises(SpatialError,match="fresh verified"):
        SpatialTools(package,req).execute("bearing",{"landmarkId":"desk"})
    req.pose.observed_at=datetime.now(timezone.utc)
    req.pose.coordinate_frame_id=uuid4()
    with pytest.raises(SpatialError):
        SpatialTools(package,req).pose()


def test_package_roundtrip_and_anchor_validation(package):
    files=files_for(package)
    saved=validate_package(zip_files(files))
    assert saved.map.manifest.id == package.manifest.id
    assert saved.map.geometry == package.geometry
    files["geometry.json"] += b" "
    with pytest.raises(PackageError,match="Checksum"):
        validate_package(zip_files(files))
    with pytest.raises(PackageError,match="anchor"):
        check_worldmap(archive_for(package),uuid4(),package.manifest.frame_anchor_id)
    with pytest.raises(PackageError,match="anchor"):
        check_worldmap(archive_for(package),package.manifest.coordinate_frame_id,uuid4())


@pytest.mark.parametrize("name",["../evil","folder/geometry.json","unexpected.json"])
def test_package_rejects_paths_and_extra_entries(package,name):
    files=files_for(package); files[name]=b"{}"
    with pytest.raises(PackageError,match="five contract"):
        validate_package(zip_files(files))


def test_duplicate_json_and_nonfinite_rejected(package):
    files=files_for(package)
    files["manifest.json"]=b'{"id":1,"id":2}'
    with pytest.raises(PackageError,match="Duplicate JSON"):
        validate_package(zip_files(files))
    files["manifest.json"]=b'{"id":NaN}'
    with pytest.raises(PackageError,match="Nonfinite"):
        validate_package(zip_files(files))


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("TOUCHSPACE_PUBLISH_CODE","test-pair-code")
    catalog=Catalog(tmp_path)
    monkeypatch.setattr(api,"get_catalog",lambda:catalog)
    monkeypatch.setattr(api,"get_chat",lambda:service_for(("overview", {})))
    api._budgets.clear()
    with TestClient(app) as client:
        yield client


def pair(client, installation=None):
    response=client.post("/api/touchspace/publishing/session",json={"code":"test-pair-code","installationId":str(installation or uuid4())})
    assert response.status_code == 200
    return {"Authorization":"Bearer "+response.json()["token"]}


def test_upload_catalog_download_and_private_authorization(client,package):
    raw=zip_files(files_for(package)); headers=pair(client)
    endpoint="/api/touchspace/maps"
    response=client.post(endpoint,headers=headers,files={"file":("map.touchspacemap",raw)})
    assert response.status_code == 201
    assert response.json()["visibility"] == "private"
    assert client.get(endpoint).json() == []
    path=endpoint+"/"+str(package.manifest.id)
    assert client.get(path).status_code == 404
    assert client.get(path+"/download").status_code == 404
    assert client.get(path,headers=pair(client)).status_code == 404
    assert client.get(path+"/download",headers=headers).content == raw
    reply=client.post("/api/touchspace/chat",headers=headers,json=question(package,pose=False).model_dump(mode="json",by_alias=True))
    assert reply.status_code == 200
    assert "West room" in reply.json()["answer"]
    assert client.post("/api/touchspace/chat",json=question(package).model_dump(mode="json",by_alias=True)).status_code == 404
    assert client.post(endpoint,headers=headers,files={"file":("map.touchspacemap",raw)}).status_code == 409


def test_publication_consent_and_search(client,package):
    raw=zip_files(files_for(package)); headers=pair(client)
    assert client.post("/api/touchspace/maps",files={"file":("m",raw)}).status_code == 401
    assert client.post("/api/touchspace/maps",headers=headers,files={"file":("m",raw)},data={"visibility":"public"}).status_code == 422
    response=client.post("/api/touchspace/maps",headers=headers,files={"file":("m",raw)},data={"visibility":"public","publication_consent":"true"})
    assert response.status_code == 201
    assert len(client.get("/api/touchspace/maps?q=synthetic").json()) == 1
    assert client.get("/api/touchspace/maps?q=%25").json() == []
    assert client.get(f"/api/touchspace/maps/{package.manifest.id}/download").content == raw


def test_pairing_expiry_and_stable_owner(client,monkeypatch):
    from app.touchspace.auth import owner
    installation=uuid4()
    headers=pair(client,installation)
    assert owner(headers["Authorization"]) == owner(pair(client,installation)["Authorization"])
    assert client.post("/api/touchspace/publishing/session",json={"code":"wrong","installationId":str(uuid4())}).status_code == 401
    import app.touchspace.auth as auth
    monkeypatch.setattr(auth.time,"time",lambda:1e20)
    with pytest.raises(Exception) as error:
        owner(headers["Authorization"])
    assert error.value.status_code == 401


def test_provider_multiple_tools_and_tool_result_wire_format(package):
    bodies=[]
    first=[THINKING,
           {"type":"tool_use","id":"t1","name":"landmark","input":{"landmarkId":"desk"}},
           {"type":"tool_use","id":"t2","name":"connectivity","input":{"roomId":"west"}}]
    def handler(request):
        # The key goes to the Anthropic API only.
        assert request.method == "POST" and str(request.url) == MESSAGES_URL
        assert "mock-secret" in request.headers.get("x-api-key","")+request.headers.get("authorization","")
        body=json.loads(request.content); bodies.append(body)
        assert "max_tokens" in body and "input_schema" in body["tools"][0]
        assert "choices" not in body and "contents" not in body
        if len(bodies)==1:
            return httpx2.Response(200,json=message(first))
        # Assistant content, thinking block included, is passed back exactly as received.
        assert body["messages"][-2] == {"role":"assistant","content":first}
        assert [b["tool_use_id"] for b in body["messages"][-1]["content"]] == ["t1","t2"]
        assert all(b["type"] == "tool_result" for b in body["messages"][-1]["content"])
        return httpx2.Response(200,json=message([{"type":"text","text":"Invented location is 999 metres left."}]))
    service=ChatService(mock_provider(handler,"mock-secret"))
    reply=asyncio.run(service.answer(package,question(package,pose=False),None))
    assert reply.provider_used
    assert "Help desk is in East room" in reply.answer
    assert "West room has confirmed doorway links to East room" in reply.answer
    assert "999" not in reply.answer
    assert len(bodies)==2


def test_claude_request_shape(package):
    requests=[]
    def handler(request):
        requests.append(request)
        body=json.loads(request.content)
        if after_tool_results(body):
            return httpx2.Response(200,json=message([{"type":"text","text":"Done"}]))
        return httpx2.Response(200,json=message([THINKING,{"type":"tool_use","id":"t1","name":"overview","input":{}}]))
    asyncio.run(ChatService(mock_provider(handler)).answer(package,question(package,pose=False),None))
    assert len(requests)==2
    for request in requests:
        body=json.loads(request.content)
        assert str(request.url) == MESSAGES_URL
        assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
        assert body["model"] == "claude-opus-5-5" and body["max_tokens"] >= 4000
        # Opus 5.5: no thinking config (disabled is a 400), effort controls latency, no forced tool choice.
        assert "thinking" not in body
        assert body["output_config"] == {"effort":"low"}
        assert body["tool_choice"] == {"type":"auto"}
        assert body["fallbacks"] == "default"
        assert "Answer every message by calling one or more tools" in body["system"]
        for tool in body["tools"]:
            schema=tool["input_schema"]
            assert tool["strict"] is True and schema["additionalProperties"] is False
            assert isinstance(schema["required"],list)
            assert not {"minLength","maxLength","minimum","maximum","minItems","maxItems"} & schema_keys(schema)


def schema_keys(node):
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in schema_keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in schema_keys(value)}
    return set()


def test_provider_omits_fallbacks_for_models_without_them(package):
    bodies=[]
    def handler(request):
        bodies.append(json.loads(request.content))
        assert "anthropic-beta" not in request.headers
        return httpx2.Response(200,json=message([{"type":"tool_use","id":"t1","name":"overview","input":{}}]))
    provider=mock_provider(handler,model="claude-haiku-5-5")
    asyncio.run(provider.send("system",[{"role":"user","content":"hi"}],[]))
    assert bodies[0]["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in bodies[0] and "tools" not in bodies[0] and "tool_choice" not in bodies[0]


@pytest.mark.parametrize("bad_call",[
 {"type":"tool_use","id":"x","name":"execute_code","input":{}},
 {"type":"tool_use","id":"x","name":"route","input":{"landmarkId":"fake","navigate":True}},
 {"type":"tool_use","id":"x","name":"bearing","input":{"landmarkId":"desk","coordinates":[1,2]}}])
def test_invalid_provider_tool_cannot_create_actions(package,bad_call):
    count=0
    def handler(request):
        nonlocal count
        count+=1
        return httpx2.Response(200,json=message([bad_call] if count==1 else [{"type":"text","text":"Done"}]))
    service=ChatService(mock_provider(handler))
    reply=asyncio.run(service.answer(package,question(package),None))
    assert not reply.actions
    assert "Unknown" in reply.answer or "Invalid" in reply.answer


def test_provider_failure_does_not_use_keyword_fallback(package):
    def handler(request):
        raise httpx2.ReadTimeout("mock timeout")
    service = ChatService(mock_provider(handler, max_retries=0))
    with pytest.raises(ChatUnavailable, match="language model"):
        asyncio.run(service.answer(package, question(package, "Is Help desk on my right?"), None))
    with pytest.raises(ChatUnavailable, match="API key"):
        asyncio.run(ChatService(MessagesProvider(ProviderConfig(None))).answer(package, question(package), None))


@pytest.mark.parametrize("respond", [
    lambda: httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    lambda: httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}),
    lambda: httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}),
    lambda: httpx2.Response(200, json=message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber"})),
    # A declined fallback chain still ends in a refusal; partial tool calls must not run.
    lambda: httpx2.Response(200, json=message([{"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-4-8"}},
                                               {"type": "tool_use", "id": "t", "name": "route", "input": {"landmarkId": "desk", "navigate": True}}],
                                              stop_reason="refusal")),
])
def test_provider_errors_and_refusals_are_unavailable(package, respond):
    def handler(request):
        return respond()
    with pytest.raises(ChatUnavailable, match="language model"):
        asyncio.run(ChatService(mock_provider(handler, max_retries=0)).answer(package, question(package), None))


def test_llm_tool_still_requires_verified_pose(package):
    reply = asyncio.run(service_for(("route", {"landmarkId": "desk", "navigate": True})).answer(
        package, question(package, "Could you escort me to the desk?", pose=False), None))
    assert not reply.actions and reply.requires_localization


def test_provider_bounded_loop_and_history(package):
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(200,json=message([{"type":"tool_use","id":str(len(calls)),"name":"overview","input":{}}]))
    service=ChatService(mock_provider(handler))
    req=question(package,pose=False)
    for _ in range(5):
        asyncio.run(service.answer(package,req,None))
    assert len(calls)==15
    assert len(next(iter(service.sessions.values())).turns) <= 8
    assert all(len(body["messages"]) <= 13 for body in calls)


def test_provider_model_ids_and_secrets_redacted():
    assert ProviderConfig("never-log-this").model == "claude-opus-5-5"
    assert "never-log-this" not in repr(ProviderConfig("never-log-this"))
    with pytest.raises(ValueError):
        ProviderConfig(None,model="bad model\n")
    with pytest.raises(ValueError):
        ProviderConfig(None,max_tokens=500)  # thinking tokens count against max_tokens


def test_provider_config_reads_only_the_anthropic_key(monkeypatch):
    for name in ("ANTHROPIC_API_KEY","TOUCHSPACE_LLM_MODEL","TOUCHSPACE_LLM_MAX_TOKENS","TOUCHSPACE_LLM_TIMEOUT"):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY","third-party-key")
    config=ProviderConfig.from_env()
    assert config.api_key is None
    assert (config.model,config.max_tokens,config.timeout) == ("claude-opus-5-5",4000,30)
    monkeypatch.setenv("ANTHROPIC_API_KEY","anthropic-key")
    monkeypatch.setenv("TOUCHSPACE_LLM_MODEL","claude-sonnet-5-5")
    config=ProviderConfig.from_env()
    assert (config.api_key,config.model) == ("anthropic-key","claude-sonnet-5-5")


def test_missing_wall_does_not_authorize_room_transition(package):
    package.geometry.walls=[w for w in package.geometry.walls if w.id != "divider"]
    package.navigation.doors=[]
    engine=SpatialEngine(package)
    assert not engine.clear_segment(Point(x=3.8,z=2.5),Point(x=4.2,z=2.5))
    with pytest.raises(SpatialError):
        engine.route(Point(x=3.5,z=2.5),"desk")


def test_declared_upload_limit_before_multipart_parsing(client):
    response=client.post("/api/touchspace/maps",content=b"short",headers={"Content-Length":str(70*1024*1024)})
    assert response.status_code == 413


def test_confirmed_passage_bridges_only_wall_thickness(package):
    package.geometry.rooms[0].polygon[1].x = 3.9
    package.geometry.rooms[0].polygon[2].x = 3.9
    package.geometry.rooms[1].polygon[0].x = 4.1
    package.geometry.rooms[1].polygon[3].x = 4.1
    engine=SpatialEngine(package)
    assert engine.walkable(Point(x=4,z=2.7))
    assert engine.room_at(Point(x=4,z=2.7)) is not None
    assert engine.route(Point(x=3.5,z=2.7),"desk")["distance"] > 0
    package.navigation.doors[0].traversability="unknown"
    assert not SpatialEngine(package).walkable(Point(x=4,z=2.7))


def test_navigation_intent_comes_from_typed_llm_arguments(package):
    # Paraphrases need no matching magic words; distance-only requests create no action.
    for navigate in (False, True):
        reply = asyncio.run(service_for(("route", {"landmarkId": "desk", "navigate": navigate})).answer(
            package, question(package, "Could you escort me to the service counter?"), None))
        assert bool(reply.actions) == navigate
        if navigate:
            assert reply.actions[0].type == "navigate"


def test_public_read_ignores_expired_publishing_credential(client,package):
    raw=zip_files(files_for(package))
    response=client.post("/api/touchspace/maps",headers=pair(client),files={"file":("map",raw)},data={"visibility":"public","publication_consent":"true"})
    assert response.status_code == 201
    headers={"Authorization":"Bearer expired.invalid"}
    assert client.get(f"/api/touchspace/maps/{package.manifest.id}/download",headers=headers).status_code == 200
    assert client.post("/api/touchspace/chat",headers=headers,json=question(package,pose=False).model_dump(mode="json",by_alias=True)).status_code == 200


def test_chunked_upload_limit_is_413_during_multipart_read(client,monkeypatch):
    from app.touchspace import limits
    monkeypatch.setattr(limits,"MAX_PACKAGE",8)
    prefix=b'--testboundary\r\nContent-Disposition: form-data; name="file"; filename="map.touchspacemap"\r\nContent-Type: application/zip\r\n\r\n'
    chunks=iter([prefix,*([b"a"*4096]*20),b'\r\n--testboundary--\r\n'])
    response=client.post("/api/touchspace/maps",content=chunks,headers={**pair(client),"Content-Type":"multipart/form-data; boundary=testboundary"})
    assert response.status_code == 413


def test_llm_clarifies_duplicate_destination_labels(package):
    duplicate = package.landmarks.landmarks[0].model_copy(update={"id": "other-desk", "room_id": "west", "position": Point(x=1, z=2.5)})
    package.landmarks.landmarks.append(duplicate)
    reply = asyncio.run(service_for(("clarify", {"question": "Which Help desk: West room or East room?"})).answer(
        package, question(package, "Where is Help desk?"), None))
    assert "Which Help desk" in reply.answer and not reply.actions


def test_inline_context_answers_without_catalog_upload(client, package, monkeypatch):
    monkeypatch.setattr(api, "get_chat", lambda: service_for(("landmark", {"landmarkId": "desk"})))
    body = question(package, "Where could I get assistance?", pose=False).model_dump(mode="json", by_alias=True)
    body["mapPackage"] = package.model_dump(mode="json", by_alias=True)
    response = client.post("/api/touchspace/chat", json=body)
    assert response.status_code == 200
    assert response.json()["providerUsed"] and "Help desk is in East room" in response.json()["answer"]
    assert client.get("/api/touchspace/maps").json() == []
    body["mapId"] = str(uuid4())
    assert client.post("/api/touchspace/chat", json=body).status_code == 422


def test_chat_reports_provider_unavailable_as_503(client, package, monkeypatch):
    monkeypatch.setattr(api, "get_chat", lambda: ChatService(MessagesProvider(ProviderConfig(None))))
    body = question(package, "Where is Help desk?", pose=False).model_dump(mode="json", by_alias=True)
    body["mapPackage"] = package.model_dump(mode="json", by_alias=True)
    response = client.post("/api/touchspace/chat", json=body)
    assert response.status_code == 503 and "API key" in response.json()["detail"]


def test_tool_loop_budget_stays_under_ios_timeout(package, monkeypatch):
    from app.touchspace import chat
    assert chat.LOOP_BUDGET_S < 40  # APIClient.swift gives /chat 40 s
    monkeypatch.setattr(chat, "LOOP_BUDGET_S", 0.2)
    async def slow(request):
        await asyncio.sleep(5)
        return httpx2.Response(200, json=message([{"type": "text", "text": "late"}]))
    started = time.monotonic()
    with pytest.raises(ChatUnavailable, match="language model"):
        asyncio.run(ChatService(mock_provider(slow, max_retries=0)).answer(package, question(package), None))
    assert time.monotonic() - started < 3


def test_chat_rejects_text_only_provider_without_keyword_fallback(package):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=message([THINKING, {"type": "text", "text": "999 metres left"}]))
    with pytest.raises(ChatUnavailable):
        asyncio.run(ChatService(mock_provider(handler)).answer(package, question(package, "Where is Help desk?"), None))
    # tool_choice "auto" cannot force a call, so the loop re-prompts exactly once.
    assert len(bodies) == 2
    assert bodies[1]["messages"][-2] == {"role": "assistant", "content": [THINKING, {"type": "text", "text": "999 metres left"}]}
    assert "calling one of the spatial tools" in bodies[1]["messages"][-1]["content"][0]["text"]


def test_text_only_reply_is_reprompted_into_a_tool_call(package):
    def handler(request):
        body = json.loads(request.content)
        if after_tool_results(body):
            return httpx2.Response(200, json=message([{"type": "text", "text": "Done"}]))
        if len(body["messages"]) == 1:
            return httpx2.Response(200, json=message([{"type": "text", "text": "It is in the east room."}]))
        return httpx2.Response(200, json=message([{"type": "tool_use", "id": "t", "name": "landmark", "input": {"landmarkId": "desk"}}]))
    reply = asyncio.run(ChatService(mock_provider(handler)).answer(package, question(package, "Where is Help desk?", pose=False), None))
    assert reply.answer == "Help desk is in East room."


def virtual_question(package, message="Could you escort me to the service counter?"):
    req = question(package, message, pose=False)
    req.simulated_pose = SimulatedPose(position=Point(x=1, z=2.5), heading=0,
        coordinate_frame_id=package.manifest.coordinate_frame_id, observed_at=datetime.now(timezone.utc))
    return req


def test_virtual_tools_and_actions_never_claim_physical_tracking(package):
    package.manifest.provenance = "synthetic-fixture"
    req = virtual_question(package)
    reply = asyncio.run(service_for(("position", {}), ("bearing", {"landmarkId": "desk"}),
        ("route", {"landmarkId": "desk", "navigate": True})).answer(package, req, None))
    assert reply.provider_used
    assert "virtual position" in reply.answer and "virtual camera" in reply.answer
    assert "Simulation route" in reply.answer
    assert [a.type for a in reply.actions] == ["simulateNavigation"]
    assert reply.actions[0].destination_id == "desk"
    # A fixture cannot use a physical pose even when the caller asserts verification.
    with pytest.raises(SpatialError, match="synthetic fixture"):
        SpatialTools(package, question(package)).pose()


def test_virtual_pose_validation_and_exclusive_contract(package):
    req = virtual_question(package)
    with pytest.raises(SpatialError, match="only supported"):
        SpatialTools(package, req).pose()
    package.manifest.provenance = "synthetic-fixture"
    req.simulated_pose.coordinate_frame_id = uuid4()
    with pytest.raises(SpatialError, match="coordinate frame"):
        SpatialTools(package, req).pose()
    req.simulated_pose.coordinate_frame_id = package.manifest.coordinate_frame_id
    req.simulated_pose.observed_at -= timedelta(seconds=10)
    with pytest.raises(SpatialError, match="fresh virtual"):
        SpatialTools(package, req).pose()
    req.simulated_pose.observed_at = datetime.now(timezone.utc)
    req.simulated_pose.position = Point(x=-10, z=-10)
    with pytest.raises(SpatialError, match="outside navigable"):
        SpatialTools(package, req).pose()
    body = req.model_dump(mode="json")
    body["pose"] = question(package).pose.model_dump(mode="json")
    with pytest.raises(ValueError, match="cannot be combined"):
        ChatRequest.model_validate(body)


def test_chat_context_declared_and_chunked_size_limits(client):
    assert client.post("/api/touchspace/chat", content=b"{}", headers={"Content-Length": str(3*1024*1024)}).status_code == 413
    chunks = iter([b" "*65536 for _ in range(33)])
    assert client.post("/api/touchspace/chat", content=chunks, headers={"Content-Type": "application/json"}).status_code == 413


def test_inline_context_rejects_invalid_navigation_geometry(client, package):
    from app.touchspace.models import Node, Edge
    package.navigation.nodes = [Node(id="a", position=Point(x=1, z=2.5), room_id="west"),
                                Node(id="b", position=Point(x=3.5, z=2.5), room_id="west")]
    package.navigation.edges = [Edge(source="a", target="b", confirmed=True, clearance=.3)]
    body = question(package, pose=False).model_dump(mode="json", by_alias=True)
    body["mapPackage"] = package.model_dump(mode="json", by_alias=True)
    response = client.post("/api/touchspace/chat", json=body)
    assert response.status_code == 422 and "graph edge" in response.json()["detail"]


@pytest.mark.parametrize("payload", [[], {"content": [None]}, {"content": "invalid"}])
def test_malformed_provider_response_is_unavailable_without_keyword_fallback(package, payload):
    provider = mock_provider(lambda _: httpx2.Response(200, json=payload))
    with pytest.raises(ChatUnavailable):
        asyncio.run(ChatService(provider).answer(package, question(package, "Where is Help desk?"), None))


def test_online_follow_up_uses_llm_history_and_previous_destination(package):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        if not after_tool_results(body):
            requests.append(body)
            name, args = ("landmark", {"landmarkId": "desk"}) if len(requests) == 1 else ("route", {"landmarkId": "desk", "navigate": True})
            return httpx2.Response(200, json=message([THINKING, {"type": "tool_use", "id": "t", "name": name, "input": args}]))
        return httpx2.Response(200, json=message([{"type": "text", "text": "Done"}]))
    service = ChatService(mock_provider(handler))
    req = question(package, "Where could I get assistance?")
    asyncio.run(service.answer(package, req, None))
    req.message = "I'd appreciate an escort there."
    reply = asyncio.run(service.answer(package, req, None))
    assert reply.provider_used and reply.actions[0].destination_id == "desk"
    assert '"previousDestinationId": "desk"' in requests[1]["system"]
    assert requests[1]["messages"][0]["content"] == "Where could I get assistance?"


def test_inline_conversation_survives_dictionary_key_order(client, package, monkeypatch):
    service = service_for(("landmark", {"landmarkId": "desk"}))
    monkeypatch.setattr(api, "get_chat", lambda: service)
    package.manifest.checksums = {"geometry.json": "a", "landmarks.json": "b"}
    body = question(package, pose=False).model_dump(mode="json", by_alias=True)
    body["mapPackage"] = package.model_dump(mode="json", by_alias=True)
    assert client.post("/api/touchspace/chat", json=body).status_code == 200
    body["mapPackage"]["manifest"]["checksums"] = {"landmarks.json": "b", "geometry.json": "a"}
    body["message"] = "What about there?"
    assert client.post("/api/touchspace/chat", json=body).status_code == 200
    assert len(service.sessions) == 1
    assert len(next(iter(service.sessions.values())).turns) == 4


def test_clarification_or_failed_tool_suppresses_actions(package):
    reply = asyncio.run(service_for(("route", {"landmarkId": "desk", "navigate": True}),
        ("clarify", {"question": "Which destination do you mean?"})).answer(package, question(package), None))
    assert not reply.actions
