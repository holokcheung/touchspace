"""Reproducible map-only venue fixture; never fabricates ARWorldMap data."""
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FRAME = '640467b6-7b58-4fc4-a35d-e45ea048ea5d'

def p(x, z): return dict(x=x, z=z)
def rect(x1,z1,x2,z2): return [p(x1,z1),p(x2,z1),p(x2,z2),p(x1,z2)]

def build():
    manifest = dict(schemaVersion=1, mapId='touchspace-demo', title='Small venue demo', floor='Ground floor', coverage='Lobby, gallery, and disconnected store room', contributor='Touchspace AI synthetic fixture', createdAt='2026-10-24T00:00:00Z', updatedAt='2026-10-24T00:00:00Z', verification='unverified', units='meters', coordinateFrameId=FRAME, frameAnchorId='c5c8c05a-f7ee-4be9-a868-31b319f52b12', worldMapIncluded=False, synthetic=True)
    geometry = dict(coordinateFrameId=FRAME, transform=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1], rooms=[dict(id='lobby',name='Lobby',polygon=rect(0,0,4,4)),dict(id='gallery',name='Gallery',polygon=rect(4,0,8,4)),dict(id='store',name='Store room',polygon=rect(9,0,11,4))], walls=[dict(id='divider-a',a=p(4,0),b=p(4,1.4)),dict(id='divider-b',a=p(4,2.6),b=p(4,4))], obstacles=[dict(id='cabinet',polygon=rect(1,2.7,1.6,3.5))], capturedRoom=None)
    nodes=[dict(id=n,position=p(x,2),roomId=r) for n,x,r in [('entry',1,'lobby'),('lobby-center',3,'lobby'),('gallery-center',5,'gallery'),('exit',7,'gallery'),('store-center',10,'store')]]
    nav=dict(coordinateFrameId=FRAME,clearance=0.3,nodes=nodes,edges=[dict(a='entry',b='lobby-center',doorId=None),dict(a='lobby-center',b='gallery-center',doorId='gallery-door'),dict(a='gallery-center',b='exit',doorId=None)],doors=[dict(id='gallery-door',name='Gallery doorway',rooms=['lobby','gallery'],position=p(4,2),width=1.2,traversable=True)])
    landmarks=dict(coordinateFrameId=FRAME,landmarks=[dict(id='front-entrance',name='Front entrance',type='entrance',position=p(1,2),roomId='lobby',nodeId='entry',provenance='volunteer'),dict(id='main-exit',name='Exit',type='exit',position=p(7,2),roomId='gallery',nodeId='exit',provenance='volunteer'),dict(id='store-shelf',name='Store shelf',type='object',position=p(10,2),roomId='store',nodeId='store-center',provenance='scan')])
    return {'manifest.json':manifest,'geometry.json':geometry,'landmarks.json':landmarks,'navigation.json':nav}

if __name__=='__main__':
    directory=ROOT/'touchspace-demo'
    directory.mkdir(exist_ok=True)
    with ZipFile(ROOT/'touchspace-demo.touchspacemap','w',ZIP_DEFLATED) as archive:
        for name,data in build().items():
            raw=json.dumps(data,indent=2)+'\n'
            (directory/name).write_text(raw)
            archive.writestr(name,raw)
    vectors=dict(route=dict(start='entry',end='exit',nodeIds=['entry','lobby-center','gallery-center','exit'],distanceMeters=6),unreachable=dict(start='entry',end='store-center'),directions=[dict(position=p(3,2),target=p(5,2),heading=h,direction=d) for h,d in [(0,'right'),(1.5707963267948966,'ahead'),(-1.5707963267948966,'behind'),(3.141592653589793,'left')]])
    (ROOT/'spatial-test-vectors.json').write_text(json.dumps(vectors,indent=2)+'\n')
