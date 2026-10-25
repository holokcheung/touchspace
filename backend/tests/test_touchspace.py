"""Portable contract/API/route/provider tests. No physical localization is claimed."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import plistlib
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.touchspace import api
from app.touchspace.chat import ChatService, MessagesProvider, ProviderConfig, SpatialTools
from app.touchspace.models import ChatRequest, MapPackage, Point, Pose
from app.touchspace.package import PackageError, check_worldmap, validate_package
from app.touchspace.spatial import SpatialEngine, SpatialError
from app.touchspace.storage import Catalog

FIXTURE = json.loads((Path(__file__).resolve().parents[2]/"shared/fixtures/routes.json").read_text())


@pytest.fixture
def package():
    return MapPackage.model_validate(copy.deepcopy(FIXTURE["package"]))


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
    monkeypatch.setattr(api,"get_chat",lambda:ChatService(MessagesProvider(ProviderConfig(None))))
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
    def handler(request):
        assert request.url.path == "/api/v1/messages"
        assert request.headers["authorization"] == "Bearer mock-secret"
        body=json.loads(request.content); bodies.append(body)
        assert "max_tokens" in body and "input_schema" in body["tools"][0]
        assert "choices" not in body and "contents" not in body
        if len(bodies)==1:
            return httpx.Response(200,json={"content":[
                {"type":"tool_use","id":"t1","name":"landmark","input":{"landmarkId":"desk"}},
                {"type":"tool_use","id":"t2","name":"connectivity","input":{"roomId":"west"}}]})
        assert body["messages"][-1]["content"][0]["type"] == "tool_result"
        return httpx.Response(200,json={"content":[{"type":"text","text":"Invented location is 999 metres left."}]})
    service=ChatService(MessagesProvider(ProviderConfig("mock-secret"),httpx.MockTransport(handler)))
    reply=asyncio.run(service.answer(package,question(package,pose=False),None))
    assert reply.provider_used
    assert "Help desk is in East room" in reply.answer
    assert "West room has confirmed doorway links to East room" in reply.answer
    assert "999" not in reply.answer
    assert len(bodies)==2


@pytest.mark.parametrize("bad_call",[
 {"type":"tool_use","id":"x","name":"execute_code","input":{}},
 {"type":"tool_use","id":"x","name":"route","input":{"landmarkId":"fake","navigate":True}},
 {"type":"tool_use","id":"x","name":"bearing","input":{"landmarkId":"desk","coordinates":[1,2]}}])
def test_invalid_provider_tool_cannot_create_actions(package,bad_call):
    count=0
    def handler(request):
        nonlocal count
        count+=1
        return httpx.Response(200,json={"content":[bad_call] if count==1 else [{"type":"text","text":"Done"}]})
    service=ChatService(MessagesProvider(ProviderConfig("mock"),httpx.MockTransport(handler)))
    reply=asyncio.run(service.answer(package,question(package),None))
    assert not reply.actions
    assert "Unknown" in reply.answer or "Invalid" in reply.answer


def test_provider_failure_fallback_and_no_pose_action(package):
    def handler(request):
        raise httpx.ReadTimeout("mock timeout")
    service=ChatService(MessagesProvider(ProviderConfig("mock"),httpx.MockTransport(handler)))
    req=question(package,"Is Help desk on my right?")
    reply=asyncio.run(service.answer(package,req,None))
    assert "right" in reply.answer and not reply.actions
    reply=asyncio.run(service.answer(package,question(package,"Navigate to Help desk",pose=False),None))
    assert not reply.actions and reply.requires_localization


def test_provider_bounded_loop_and_history(package):
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={"content":[{"type":"tool_use","id":str(len(calls)),"name":"overview","input":{}}]})
    service=ChatService(MessagesProvider(ProviderConfig("mock"),httpx.MockTransport(handler)))
    req=question(package,pose=False)
    for _ in range(5):
        asyncio.run(service.answer(package,req,None))
    assert len(calls)==15
    assert len(next(iter(service.sessions.values())).turns) <= 8
    assert all(len(body["messages"]) <= 13 for body in calls)


def test_provider_model_ids_and_secrets_redacted():
    assert ProviderConfig("never-log-this",model="qwen/qwen3.7-flash").model
    assert "never-log-this" not in repr(ProviderConfig("never-log-this"))
    with pytest.raises(ValueError):
        ProviderConfig(None,model="bad model\n")


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


def test_navigation_action_requires_explicit_user_request(package):
    for text in ["Describe the map","Do not navigate to Help desk"]:
        tools=SpatialTools(package,question(package,text))
        tools.execute("route",{"landmarkId":"desk","navigate":True})
        assert not tools.actions
    tools=SpatialTools(package,question(package,"Please guide me to Help desk"))
    tools.execute("route",{"landmarkId":"desk","navigate":True})
    assert tools.actions[0].destination_id == "desk"


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


def test_provider_cannot_arbitrarily_resolve_duplicate_destination_label(package):
    duplicate=package.landmarks.landmarks[0].model_copy(update={"id":"other-desk","room_id":"west","position":Point(x=1,z=2.5)})
    package.landmarks.landmarks.append(duplicate)
    tools=SpatialTools(package,question(package,"Navigate to Help desk"))
    with pytest.raises(SpatialError,match="Which one"):
        tools.execute("route",{"landmarkId":"desk","navigate":True})
    assert not tools.actions
