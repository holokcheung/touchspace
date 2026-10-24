from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.touchspace.api import get_catalog
from app.touchspace.config import TouchspaceSettings, get_touchspace_settings
from app.touchspace.storage import Catalog
from tests.test_touchspace_package import archive, documents

TOKEN='test-authorization-token-at-least-24-characters'
HEADERS={'Authorization':'Bearer '+TOKEN}


@pytest.fixture
def touchspace_client(tmp_path):
    app.dependency_overrides[get_catalog]=lambda:Catalog(tmp_path/'touchspace')
    app.dependency_overrides[get_touchspace_settings]=lambda:TouchspaceSettings(TOKEN,'','gemini-3.8-flash')
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def upload(client, raw=None, **data):
    return client.post('/api/touchspace/maps',headers=HEADERS,files={'file':('venue.touchspacemap',raw or archive(),'application/zip')},data=data)


def test_private_default_and_access_control(touchspace_client):
    c=touchspace_client
    assert c.post('/api/touchspace/maps',files={'file':('x.zip',archive(),'application/zip')}).status_code==401
    raw=archive(); r=upload(c,raw); assert r.status_code==201,r.text
    assert r.json()['visibility']=='private' and r.json()['worldDataStatus']=='absent-draft'
    assert c.get('/api/touchspace/maps').json()==[]
    for suffix in ['', '/download']:
        assert c.get('/api/touchspace/maps/touchspace-demo'+suffix).status_code==404
        response=c.get('/api/touchspace/maps/touchspace-demo'+suffix,headers=HEADERS)
        assert response.status_code==200
    assert c.get('/api/touchspace/maps/touchspace-demo/download',headers=HEADERS).content==raw


def test_publication_consent_and_complete_download(touchspace_client):
    c=touchspace_client; raw=archive(world=True)
    assert upload(c,raw,visibility='public').status_code==422
    assert upload(c,visibility='public',publication_consent='true').status_code==422
    r=upload(c,raw,visibility='public',publication_consent='true'); assert r.status_code==201,r.text
    assert r.json()['worldDataStatus']=='present-unverified'
    assert len(c.get('/api/touchspace/maps?q=venue').json())==1
    assert len(c.get('/api/touchspace/maps?q=gallery').json())==1
    assert c.get('/api/touchspace/maps?q=%').json()==[]
    r=c.get('/api/touchspace/maps/touchspace-demo/download')
    assert r.content==raw and 'no-store' in r.headers['cache-control']


def test_conflicting_ids_and_invalid_uploads(touchspace_client):
    c=touchspace_client; assert upload(c).status_code==201
    d=documents();d['manifest.json']['title']='Changed title'
    assert upload(c,archive(d)).status_code==409
    assert upload(c,b'bad').status_code==422
    assert upload(c,archive(extras={'../escape':b'bad'})).status_code==422
    assert c.post('/api/touchspace/maps',headers=HEADERS,files={'file':('x.txt',b'bad','text/plain')}).status_code==415


def test_metadata_database_survives_restart(touchspace_client,tmp_path):
    raw=archive(); upload(touchspace_client,raw)
    catalog=Catalog(tmp_path/'touchspace')
    with catalog.connection() as db:
        row=db.execute('SELECT * FROM touchspace_maps').fetchone()
        assert row['checksum'] and row['schema_version']==1 and row['visibility']=='private'
        assert db.execute('PRAGMA user_version').fetchone()[0]==1
    assert catalog.path(row).read_bytes()==raw


def test_disabled_guard_and_legacy_health(touchspace_client):
    app.dependency_overrides[get_touchspace_settings]=lambda:TouchspaceSettings('','','unused')
    assert upload(touchspace_client).status_code==503
    assert touchspace_client.get('/api/health').status_code==200


def test_request_limit_rejects_before_multipart_parser(touchspace_client):
    r=touchspace_client.post('/api/touchspace/maps',content=b'small',headers={**HEADERS,'Content-Length':str(70*1024*1024),'Content-Type':'application/zip'})
    assert r.status_code==413


def test_chunked_request_limit():
    import asyncio
    from app.touchspace.middleware import PackageSizeLimit
    called=[];sent=[]
    async def downstream(scope,receive,send):called.append(True)
    messages=iter([{'type':'http.request','body':b'x'*100,'more_body':True},{'type':'http.request','body':b'y'*100,'more_body':False}])
    async def receive():return next(messages)
    async def send(message):sent.append(message)
    asyncio.run(PackageSizeLimit(downstream,max_bytes=150)({'type':'http','method':'POST','path':'/api/touchspace/maps','headers':[]},receive,send))
    assert not called and sent[0]['status']==413


def test_malformed_non_ascii_credential_is_unauthorized():
    from app.touchspace.api import authorized_owner
    assert authorized_owner('Bearer ☃',TouchspaceSettings(TOKEN,'','unused')) is None
