from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app.touchspace.chat import GeminiInterpreter, execute
from app.touchspace.config import TouchspaceSettings, get_touchspace_settings
from app.touchspace.models import ChatRequest, ToolCall
from app.touchspace.package import validate_package
from app.main import app
from tests.test_touchspace_api import HEADERS, TOKEN, touchspace_client, upload
from tests.test_touchspace_package import archive, pose


def turn(client, message, session=None, pp=None):
    body=dict(mapId='touchspace-demo',sessionId=str(session or uuid4()),message=message)
    if pp: body['pose']=pp.model_dump(mode='json')
    return client.post('/api/touchspace/chat',headers=HEADERS,json=body)


def test_map_only_grounded_overview_connections_followups(touchspace_client):
    c=touchspace_client; upload(c); session=uuid4()
    r=turn(c,'where is the exit',session); assert r.status_code==200,r.text
    assert 'main-exit' in r.json()['sourceIds'] and r.json()['action'] is None
    follow=turn(c,'tell me about it',session).json()
    assert 'main-exit' in follow['sourceIds']
    assert turn(c,'what color is the exit',session).json()['sourceIds']==[]
    assert 'unknown' in turn(c,'where is the cafeteria').json()['reply']
    r=turn(c,'how are the rooms connected?').json()
    assert 'gallery-door' in r['sourceIds'] and r['toolResults'][0]['operation']=='room_connections'
    assert turn(c,'what is to my right?').json()['action'] is None
    assert 'uncertain' in turn(c,'what is to my right?').json()['reply']


def test_live_directions_change_with_rotation_and_stop_on_tracking_loss(touchspace_client):
    raw=archive(world=True); upload(touchspace_client,raw); p=validate_package(raw); pp=pose(p)
    a=turn(touchspace_client,'what is to my right?',pp=pp).json()
    assert a['poseUsed'] and 'main-exit' in a['sourceIds']
    rotated=pp.model_copy(update={'heading':3.14159265})
    b=turn(touchspace_client,'what is to my right?',pp=rotated).json()
    assert 'main-exit' not in b['sourceIds'] and 'front-entrance' in b['sourceIds']
    for update in [dict(tracking='limited'),dict(frameVerified=False),dict(timestamp=datetime.now(timezone.utc)-timedelta(seconds=30))]:
        r=turn(touchspace_client,'take me to the exit',pp=pp.model_copy(update=update)).json()
        assert r['action'] is None and not r['poseUsed'] and r['toolResults'][0]['error']=='spatial_unavailable'


def test_reachable_unreachable_and_no_unknown_actions(touchspace_client):
    raw=archive(world=True);upload(touchspace_client,raw);pp=pose(validate_package(raw));session=uuid4()
    r=turn(touchspace_client,'take me to the exit',session,pp).json()
    assert r['action']=={'type':'destination','destinationId':'main-exit'}
    assert r['toolResults'][0]['data']['distanceMeters']==4
    r=turn(touchspace_client,'how far is it',session,pp).json()
    assert r['action']['destinationId']=='main-exit'
    r=turn(touchspace_client,'take me to the store shelf',pp=pp).json()
    assert r['action'] is None and 'unreachable' in r['reply']
    assert turn(touchspace_client,'navigate to the cafeteria',pp=pp).json()['action'] is None


def test_all_typed_operations_are_deterministic():
    p=validate_package(archive(world=True));body=ChatRequest(mapId=p.manifest.mapId,sessionId=uuid4(),message='test',pose=pose(p))
    for op in ['get_pose','list_rooms','nearby_landmarks','relative_direction','room_connections','get_route','route_summary','get_map_overview']:
        reply,data,sources,action=execute(ToolCall(operation=op,targetId='main-exit'),body,p)
        assert reply and data and sources
        if action: assert action['destinationId']=='main-exit'


def test_hosted_interpreter_is_validated_and_provider_failures_fall_back(touchspace_client,monkeypatch):
    upload(touchspace_client)
    app.dependency_overrides[get_touchspace_settings]=lambda:TouchspaceSettings(TOKEN,'test-provider-key','test-model')
    async def fake(self,*args): return ToolCall(operation='list_rooms')
    monkeypatch.setattr(GeminiInterpreter,'interpret',fake)
    r=turn(touchspace_client,'describe rooms').json();assert r['interpreter']=='gemini' and 'lobby' in r['sourceIds']
    r=turn(touchspace_client,'is the exit open?').json();assert 'unknown' in r['reply'] and r['sourceIds']==[]
    async def failed(self,*args): raise httpx.ConnectError('provider unavailable')
    monkeypatch.setattr(GeminiInterpreter,'interpret',failed)
    r=turn(touchspace_client,'describe rooms').json();assert r['interpreter']=='local-fallback-provider-unavailable' and r['sourceIds']


def test_private_chat_requires_authorization(touchspace_client):
    upload(touchspace_client)
    r=touchspace_client.post('/api/touchspace/chat',json=dict(mapId='touchspace-demo',sessionId=str(uuid4()),message='overview'))
    assert r.status_code==404


def test_gemini_http_contract_and_untrusted_outputs(monkeypatch):
    import asyncio
    import json
    package=validate_package(archive())
    real_client=httpx.AsyncClient
    outputs=iter([
        dict(operation='get_map_overview',targetId='main-exit',direction=None),
        dict(operation='get_route',targetId='invented-destination',direction=None),
        dict(operation='get_route',targetId='main-exit',reply='invented 900 meter route'),
    ])
    def handler(request):
        assert request.url.host=='generativelanguage.googleapis.com'
        assert request.headers['x-goog-api-key']=='server-only-test-key'
        payload=json.loads(request.content)
        schema=payload['generationConfig']['responseFormat']['text']['schema']
        assert 'reply' not in schema['properties'] and 'distanceMeters' not in schema['properties']
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps(next(outputs))}]}}]})
    monkeypatch.setattr('app.touchspace.chat.httpx.AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
    settings=TouchspaceSettings(TOKEN,'server-only-test-key','gemini-3.8-flash')
    interpreter=GeminiInterpreter()
    good=asyncio.run(interpreter.interpret('where is exit',package,None,settings))
    assert good.targetId=='main-exit'
    unknown=asyncio.run(interpreter.interpret('invent a destination',package,None,settings))
    assert unknown.operation=='unknown'
    with pytest.raises(ValueError):asyncio.run(interpreter.interpret('inject free form reply',package,None,settings))
