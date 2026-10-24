from __future__ import annotations

import io
import json
import math
import plistlib
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.touchspace.models import Point, Pose
from app.touchspace.package import PackageError, validate_package
from app.touchspace.spatial import SpatialError

ROOT = Path(__file__).resolve().parents[2] / 'sample-data'


def documents():
    return {p.name: json.loads(p.read_text()) for p in (ROOT / 'touchspace-demo').glob('*.json')}


def archive(docs=None, world=False, extras=None):
    docs = docs or documents()
    output = io.BytesIO()
    if world:
        docs['manifest.json']['synthetic'] = False
        docs['manifest.json']['worldMapIncluded'] = True
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in docs.items():
            z.writestr(name, json.dumps(data))
        if world:
            # Test double for the backend structural check; NOT device-restorable world data.
            z.writestr('worldmap.archive', plistlib.dumps({'$archiver':'NSKeyedArchiver','$objects':[{'$classname':'ARWorldMap'},'touchspace-frame:'+docs['manifest.json']['coordinateFrameId']]}, fmt=plistlib.FMT_BINARY))
        for name, raw in (extras or {}).items():
            z.writestr(name, raw)
    return output.getvalue()


def pose(package, **kwargs):
    return Pose(coordinateFrameId=package.manifest.coordinateFrameId, position=Point(x=3,z=2), heading=0, tracking='localized', frameVerified=True, timestamp=datetime.now(timezone.utc), **kwargs)


def test_demo_roundtrip_and_shared_vectors():
    package = validate_package((ROOT/'touchspace-demo.touchspacemap').read_bytes())
    assert not package.world_data
    assert len(package.warnings) == 2
    engine = package.engine()
    vectors = json.loads((ROOT/'spatial-test-vectors.json').read_text())
    v = vectors['route']
    route = engine.route(v['start'],v['end'])
    assert route['nodeIds'] == v['nodeIds'] and route['distanceMeters'] == v['distanceMeters']
    with pytest.raises(SpatialError, match='unreachable'):
        engine.route(**vectors['unreachable'])
    for v in vectors['directions']:
        pp = pose(package).model_copy(update={'position':Point(**v['position']), 'heading':v['heading']})
        assert engine.relative(pp, Point(**v['target']))['direction'] == v['direction']


@pytest.mark.parametrize('name', ['../manifest.json','/etc/passwd','folder/x','worldmap.archive/evil'])
def test_reject_zip_paths(name):
    with pytest.raises(PackageError): validate_package(archive(extras={name:b'x'}))


def test_reject_duplicate_entry():
    with pytest.warns(UserWarning): raw = archive(extras={'manifest.json':b'{}'})
    with pytest.raises(PackageError): validate_package(raw)


@pytest.mark.parametrize('change', ['schema','frame','nan','transform','outside','edge','wall','unknown-room','duplicate','cross-room','landmark','door-clearance'])
def test_reject_invalid_semantics(change):
    d=documents()
    if change=='schema': d['manifest.json']['schemaVersion']=2
    if change=='frame': d['geometry.json']['coordinateFrameId']='00000000-0000-0000-0000-000000000000'
    if change=='nan': d['navigation.json']['nodes'][0]['position']['x']=math.nan
    if change=='transform': d['geometry.json']['transform'][12]=2
    if change=='outside': d['navigation.json']['nodes'][0]['position']['x']=-10
    if change=='edge': d['navigation.json']['edges'][0]['b']='missing'
    if change=='wall': d['geometry.json']['walls'][0]['b']['z']=4
    if change=='unknown-room': d['navigation.json']['nodes'][0]['roomId']='unknown'
    if change=='duplicate': d['navigation.json']['nodes'].append(d['navigation.json']['nodes'][0])
    if change=='cross-room': d['navigation.json']['edges'][1]['doorId']=None
    if change=='landmark': d['landmarks.json']['landmarks'][0]['nodeId']='exit'
    if change=='door-clearance': d['navigation.json']['doors'][0]['width']=0.4
    with pytest.raises(PackageError): validate_package(archive(d))


def test_unknown_door_is_not_traversable():
    d=documents(); d['navigation.json']['doors'][0]['traversable']=False
    e=validate_package(archive(d)).engine()
    with pytest.raises(SpatialError,match='unreachable'): e.route('entry','exit')


def test_tracking_and_freshness_gate():
    package=validate_package(archive(world=True)); engine=package.engine(); pp=pose(package)
    assert engine.checked_pose(pp) == pp
    for update in [dict(tracking='limited'),dict(tracking='failed'),dict(tracking='relocalizing'),dict(frameVerified=False),dict(timestamp=datetime.now(timezone.utc)-timedelta(seconds=11)),dict(position=Point(x=-1,z=-1))]:
        with pytest.raises(SpatialError): engine.checked_pose(pp.model_copy(update=update))
    draft=validate_package(archive())
    with pytest.raises(SpatialError): draft.engine().checked_pose(pose(draft))


def test_no_snapping_through_walls():
    e=validate_package(archive()).engine()
    with pytest.raises(SpatialError): e.nearest_node(Point(x=4,z=0.2))


def test_bad_or_missing_world_archive():
    d=documents(); d['manifest.json']['worldMapIncluded']=True; d['manifest.json']['synthetic']=False
    with pytest.raises(PackageError): validate_package(archive(d))
    with pytest.raises(PackageError): validate_package(archive(extras={'worldmap.archive':b'not world data'}))


def test_empty_world_entry_and_blank_metadata_are_rejected():
    with pytest.raises(PackageError):validate_package(archive(extras={'worldmap.archive':b''}))
    d=documents();d['manifest.json']['contributor']='   '
    with pytest.raises(PackageError):validate_package(archive(d))
