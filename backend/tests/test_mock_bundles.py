"""Exercise the actual shipped bundle bytes, without LiDAR or provider requests."""
import asyncio
import io
import json
import plistlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.touchspace import api
from app.touchspace.chat import ChatService, MessagesProvider, ProviderConfig, SpatialTools
from app.touchspace.models import ChatRequest, Point, Pose
from app.touchspace.package import PackageError, check_worldmap, check_synthetic_worldmap, validate_package
from app.touchspace.spatial import SpatialEngine, SpatialError
from app.touchspace.storage import Catalog

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "sample-data/mock-maps"


@pytest.fixture(scope="module",params=["harbour-clinic","neighbourhood-library"])
def bundle(request):
    slug=request.param
    raw=(FIXTURES/(slug+".touchspacemap")).read_bytes()
    return slug,validate_package(raw)


def test_realistic_bundle_contract_and_honest_provenance(bundle):
    slug,validated=bundle
    package=validated.map
    assert package.manifest.is_synthetic
    assert package.manifest.verification == "unverified"
    assert len(package.geometry.rooms) >= 4
    assert len(package.geometry.obstacles) >= 8
    assert len(package.landmarks.landmarks) >= 6
    assert any(d.traversability != "confirmed" for d in package.navigation.doors)
    engine=SpatialEngine(package)
    assert all(engine.walkable(l.position) for l in package.landmarks.landmarks)
    with zipfile.ZipFile(io.BytesIO(validated.raw)) as archive:
        for name in archive.namelist():
            assert archive.read(name) == (FIXTURES/slug/name).read_bytes()
        world=archive.read("worldmap.archive")
        assert plistlib.loads(world)["relocalizable"] is False
        check_synthetic_worldmap(world,package.manifest.coordinate_frame_id,package.manifest.frame_anchor_id)
        with pytest.raises(PackageError):
            check_worldmap(world,package.manifest.coordinate_frame_id,package.manifest.frame_anchor_id)
        with pytest.raises(PackageError):
            check_synthetic_worldmap(world,uuid4(),package.manifest.frame_anchor_id)


def test_recorded_route_fixture_and_collision_checks(bundle):
    slug,validated=bundle
    scenarios=json.loads((FIXTURES/slug/"route-scenarios.json").read_text())
    # Test a representative route from each realistic layout, including the shelving detour.
    target="clinic-treatment" if slug=="harbour-clinic" else "library-travel"
    scenario=next(s for s in scenarios if s["destinationId"]==target)
    engine=SpatialEngine(validated.map)
    route=engine.route(Point(**scenario["start"]),target)
    assert scenario["reachable"]
    assert route["distance"] == pytest.approx(scenario["distance"],abs=1e-7)
    points=[Point(**p) for p in route["waypoints"]]
    assert all(engine.clear_segment(a,b) for a,b in zip(points,points[1:]))
    assert not engine.clear_segment(points[0],points[-1])
    assert not engine.walkable(Point(x=-1,z=-1))


def test_fixture_refuses_live_pose_even_if_client_claims_verified(bundle):
    _,validated=bundle
    package=validated.map
    request=ChatRequest(map_id=package.manifest.id,session_id=uuid4(),message="Navigate to Main entrance",
        pose=Pose(position=package.landmarks.landmarks[0].position,heading=0,
                  coordinate_frame_id=package.manifest.coordinate_frame_id,observed_at=datetime.now(timezone.utc),verified=True))
    tools=SpatialTools(package,request)
    with pytest.raises(SpatialError,match="synthetic fixture"):
        tools.execute("route",{"landmarkId":package.landmarks.landmarks[0].id,"navigate":True})
    assert not tools.actions


def test_catalog_download_and_grounded_qa_with_actual_bundle(bundle,tmp_path,monkeypatch):
    _,validated=bundle
    catalog=Catalog(tmp_path)
    catalog.save(validated,owner="fixture-test",visibility="public")
    monkeypatch.setattr(api,"get_catalog",lambda:catalog)
    monkeypatch.setattr(api,"get_chat",lambda:ChatService(MessagesProvider(ProviderConfig(None))))
    api._budgets.clear()
    with TestClient(app) as client:
        response=client.get("/api/touchspace/maps?q=synthetic")
        assert response.status_code == 200 and len(response.json()) == 1
        map_id=str(validated.map.manifest.id)
        assert response.json()[0]["manifest"]["provenance"] == "synthetic-fixture"
        assert client.get(f"/api/touchspace/maps/{map_id}/download").content == validated.raw
        response=client.post("/api/touchspace/chat",json={"mapId":map_id,"sessionId":str(uuid4()),"message":"Describe the map"})
        assert response.status_code == 200
        assert "Synthetic test map" in response.json()["answer"]
        assert not response.json()["actions"]
        place=validated.map.landmarks.landmarks[1]
        response=client.post("/api/touchspace/chat",json={"mapId":map_id,"sessionId":str(uuid4()),"message":"Where is "+place.name+"?"})
        assert place.name in response.json()["answer"]
        assert not response.json()["actions"]


def test_clinic_unknown_staff_door_refuses_route():
    package=validate_package((FIXTURES/"harbour-clinic.touchspacemap").read_bytes()).map
    with pytest.raises(SpatialError,match="No validated route"):
        SpatialEngine(package).route(Point(x=13.5,z=6),"clinic-supplies")


def test_library_duplicate_name_requires_clarification():
    package=validate_package((FIXTURES/"neighbourhood-library.touchspacemap").read_bytes()).map
    request=ChatRequest(map_id=package.manifest.id,session_id=uuid4(),message="Where is Study desk?")
    reply=asyncio.run(ChatService(MessagesProvider(ProviderConfig(None))).answer(package,request,None))
    assert "Which destination" in reply.answer
    assert "Reading room" in reply.answer and "Children's room" in reply.answer
    assert not reply.actions
