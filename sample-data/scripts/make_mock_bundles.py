#!/usr/bin/env python3
"""Reproducible fictional venues. No Apple world map or physical scan is fabricated.

Run from anywhere with backend/.venv/bin/python. No network or provider keys needed.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import plistlib
import sqlite3
import sys
import zipfile
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.touchspace.models import MapPackage, Point
from app.touchspace.package import validate_package
from app.touchspace.spatial import SpatialEngine, SpatialError, inside


def point(x, z):
    return {"x": x, "z": z}


def rectangle(x, z, width, depth):
    return [point(x,z), point(x+width,z), point(x+width,z+depth), point(x,z+depth)]


def room(id, name, x, z, width, depth):
    return {"id":id, "name":name, "polygon":rectangle(x,z,width,depth)}


def wall(id, x1, z1, x2, z2):
    return {"id":id, "start":point(x1,z1), "end":point(x2,z2), "thickness":0.15}


def furniture(id, x, z, width, depth):
    return {"id":id, "polygon":rectangle(x,z,width,depth)}


def landmark(id, name, room_id, x, z, kind="destination"):
    return {"id":id, "name":name, "roomId":room_id, "position":point(x,z), "kind":kind}


def door(id, wall_id, rooms, x1, z1, x2, z2, state="confirmed"):
    return {"id":id, "wallId":wall_id, "roomIds":rooms, "start":point(x1,z1), "end":point(x2,z2), "traversability":state}


def manifest(slug, venue, coverage):
    def uuid(kind):
        return str(uuid5(NAMESPACE_URL, f"https://touchspace.invalid/fixtures/{slug}/{kind}/v1"))
    return {"schemaVersion":"1.0", "id":uuid("map"), "venue":venue, "floor":"Ground floor",
            "coverage":coverage, "contributor":"TouchSpace synthetic test fixtures", "verification":"unverified",
            "createdAt":"2026-10-25T00:00:00Z", "coordinateFrameId":uuid("frame"), "frameAnchorId":uuid("anchor"),
            "provenance":"synthetic-fixture", "checksums":{}}


def outer_walls(width, depth):
    return [wall("outer-front",0,0,width,0), wall("outer-right",width,0,width,depth),
            wall("outer-back",width,depth,0,depth), wall("outer-left",0,depth,0,0)]


def clinic():
    return {
        "manifest":manifest("harbour-clinic", "Harbour Community Clinic (Synthetic)", "contiguous-zone"),
        "geometry":{
            "floorY":0, "mapToWorld":{"x":0,"z":0,"yaw":0,"y":0},
            "rooms":[room("waiting","Reception and waiting",0,0,6,6), room("consult","Consultation room",0,6,6,4),
                     room("hall","Main corridor",6,0,3,10), room("wc","Accessible restroom",9,0,3,5),
                     room("treatment","Treatment room",9,5,6,5), room("store","Staff supplies",12,0,3,5)],
            "walls":outer_walls(15,10)+[wall("waiting-consult",0,6,6,6),wall("west-hall",6,0,6,10),
                     wall("east-hall",9,0,9,10),wall("wc-store",12,0,12,5),wall("south-treatment",9,5,15,5)],
            "obstacles":[furniture("reception-counter",.8,.8,2.8,1), furniture("waiting-chairs-west",.4,3.5,.7,2),
                         furniture("waiting-chairs-back",3,4.8,2.2,.7),furniture("waiting-coffee-table",2.4,3,.9,1.3),
                         furniture("consult-desk",.8,6.7,1.9,.8),furniture("exam-couch",.7,8.5,2,.9),
                         furniture("wc-basin",9.6,.5,.8,.7),furniture("wc-toilet",10.6,3.5,1,1.1),
                         furniture("treatment-bed",10,8.6,2.5,.9),furniture("medical-cabinet",13.9,5.7,.7,1.9),
                         furniture("stock-cabinets",13,.5,1.4,.8)]},
        "landmarks":{"landmarks":[landmark("clinic-entrance","Main entrance","waiting",1,2.4,"entrance"),
            landmark("clinic-reception","Reception desk","waiting",3.8,2.4,"information"),
            landmark("clinic-consult","Consultation room","consult",4,8),
            landmark("clinic-restroom","Accessible restroom","wc",10.4,2.5,"restroom"),
            landmark("clinic-treatment","Treatment bed","treatment",11.5,8),
            landmark("clinic-supplies","Staff supplies","store",13.5,2.3)]},
        "navigation":{"resolution":.1,"clearance":.3,"nodes":[],"edges":[],"doors":[
            door("waiting-hall-door","west-hall",["waiting","hall"],6,2.2,6,3.6),
            door("consult-hall-door","west-hall",["consult","hall"],6,7,6,8.3),
            door("restroom-hall-door","east-hall",["wc","hall"],9,1.8,9,3.1),
            door("treatment-hall-door","east-hall",["treatment","hall"],9,6.6,9,8),
            door("supplies-door","south-treatment",["store","treatment"],13,5,14.2,5,"unknown")]}}


def library():
    return {
        "manifest":manifest("neighbourhood-library", "Neighbourhood Library (Synthetic)", "partial"),
        "geometry":{
            "floorY":0,"mapToWorld":{"x":4,"z":-2,"yaw":math.pi/6,"y":0},
            "rooms":[room("foyer","Entrance and returns",0,0,6,4), room("children","Children's room",6,0,4,4),
                     room("reading","Reading room",0,4,10,6), room("stacks","Book stacks",10,0,6,10)],
            "walls":outer_walls(16,10)+[wall("foyer-children",6,0,6,4),wall("front-reading",0,4,10,4),wall("stacks-divider",10,0,10,10)],
            "obstacles":[furniture("returns-counter",.7,.5,2.5,.8),furniture("kids-bookcase",6.5,.6,2.9,.7),
                         furniture("reading-table",3,5.5,3,1.8),furniture("west-study-table",1,8,1.3,1.2),
                         furniture("quiet-desks",4,8.6,4.8,.8),furniture("shelf-a",11.2,1,.6,7.7),
                         furniture("shelf-b",12.9,1,.6,7.7),furniture("shelf-c",14.6,1,.6,6.5)]},
        "landmarks":{"landmarks":[landmark("library-entrance","Main entrance","foyer",1.2,2.8,"entrance"),
            landmark("library-returns","Returns desk","foyer",3.6,1.9,"information"),
            landmark("library-study-reading","Study desk","reading",2.4,7.6),
            landmark("library-study-children","Study desk","children",8.5,2.5),
            landmark("library-quiet","Quiet reading corner","reading",7.8,8),
            landmark("library-travel","Travel books","stacks",12.35,6.5),
            landmark("library-staff-boundary","Unscanned staff-area boundary","stacks",15,9.1,"boundary")]},
        "navigation":{"resolution":.1,"clearance":.3,"nodes":[],"edges":[],"doors":[
            door("foyer-reading-door","front-reading",["foyer","reading"],2,4,3.4,4),
            door("children-reading-door","front-reading",["children","reading"],7,4,8.3,4),
            door("reading-stacks-door","stacks-divider",["reading","stacks"],10,6,10,7.4),
            door("children-stacks-door","stacks-divider",["children","stacks"],10,1.6,10,2.8,"blocked"),
            door("staff-boundary-door","outer-right",["stacks"],16,8.1,16,9.5,"unknown")]}}


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()


def add_graph(data):
    package = MapPackage.model_validate(data)
    engine = SpatialEngine(package)
    nodes = [{"id":"node-"+l.id,"roomId":l.room_id,"position":l.position.model_dump()} for l in package.landmarks.landmarks]
    for d in package.navigation.doors:
        if d.traversability != "confirmed" or len(d.room_ids) != 2:
            continue
        dx,dz=d.end.x-d.start.x,d.end.z-d.start.z
        length=math.hypot(dx,dz)
        for side in [-1,1]:
            p=Point(x=(d.start.x+d.end.x)/2-side*dz/length*.6,z=(d.start.z+d.end.z)/2+side*dx/length*.6)
            r=next((r for r in package.geometry.rooms if r.id in d.room_ids and inside(p,r.polygon)),None)
            if r and engine.walkable(p):
                nodes.append({"id":d.id+"-"+r.id,"roomId":r.id,"position":p.model_dump()})
    edges=[]
    for i,a in enumerate(nodes):
        for b in nodes[i+1:]:
            pa,pb=Point(**a["position"]),Point(**b["position"])
            if a["roomId"] != b["roomId"] and pa.x != pb.x and pa.z != pb.z:
                continue
            if engine.clear_segment(pa,pb):
                edges.append({"source":a["id"],"target":b["id"],"confirmed":True,"clearance":.3})
    data["navigation"]["nodes"],data["navigation"]["edges"]=nodes,edges
    return MapPackage.model_validate(data)


def scenarios(package):
    engine=SpatialEngine(package)
    prefix="clinic" if "Clinic" in package.manifest.venue else "library"
    start=next(l for l in package.landmarks.landmarks if l.id==prefix+"-entrance")
    result=[]
    for destination in package.landmarks.landmarks:
        if destination.id==start.id:
            continue
        item={"originId":start.id,"start":start.position.model_dump(),"destinationId":destination.id}
        try:
            route=engine.route(start.position,destination.id)
            item.update(reachable=True,distance=route["distance"],waypoints=route["waypoints"])
        except SpatialError as exc:
            item.update(reachable=False,error=str(exc))
        result.append(item)
    return result


def preview(package, routes):
    """Standalone vector plan, exported from exactly the bundled geometry."""
    scale=44; offset_x=30; offset_z=90
    def coord(p):
        return (p.x*scale+offset_x,p.z*scale+offset_z)
    def polygon(points):
        return " ".join(f"{x:.2f},{z:.2f}" for x,z in map(coord,points))
    colors=["#dcf0ff","#fbe9d0","#e2f4e3","#eee1fb","#fce0e3","#e3e7ea"]
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1160" height="660" viewBox="0 0 1160 660">',
         '<rect width="1160" height="660" fill="#fff"/>',
         f'<text x="30" y="30" font-family="sans-serif" font-size="24" font-weight="bold">{html.escape(package.manifest.venue)}</text>',
         '<text x="30" y="57" font-family="sans-serif" font-size="14">FICTIONAL TEST DATA · metres on X/Z floor plane · no physical AR localization</text>']
    for i,r in enumerate(package.geometry.rooms):
        svg.append(f'<polygon points="{polygon(r.polygon)}" fill="{colors[i%len(colors)]}" stroke="#aaa"/>')
        svg.append(f'<rect x="795" y="{94+i*25}" width="16" height="16" fill="{colors[i%len(colors)]}" stroke="#888"/>')
        svg.append(f'<text x="820" y="{107+i*25}" font-family="sans-serif" font-size="14">{html.escape(r.name)}</text>')
    for o in package.geometry.obstacles:
        svg.append(f'<polygon points="{polygon(o.polygon)}" fill="#7c8591" stroke="#4b5563"/>')
    for w in package.geometry.walls:
        a,b=coord(w.start),coord(w.end)
        svg.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#182433" stroke-width="6"/>')
    for d in package.navigation.doors:
        a,b=coord(d.start),coord(d.end)
        color={"confirmed":"#059669","blocked":"#be123c","unknown":"#c77800"}[d.traversability]
        svg.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="7"/>')
    destination="clinic-treatment" if "Clinic" in package.manifest.venue else "library-travel"
    route=next(r for r in routes if r["destinationId"]==destination)
    if route["reachable"]:
        points=[Point(**p) for p in route["waypoints"]]
        svg.append(f'<polyline points="{polygon(points)}" fill="none" stroke="#1d4ed8" stroke-width="3" stroke-dasharray="7 4"/>')
    for i,l in enumerate(package.landmarks.landmarks,1):
        x,z=coord(l.position)
        svg.extend([f'<circle cx="{x}" cy="{z}" r="11" fill="#fff" stroke="#111827" stroke-width="1.5"/>',
                    f'<text x="{x}" y="{z+5}" text-anchor="middle" font-family="sans-serif" font-size="13">{i}</text>',
                    f'<text x="795" y="{310+i*25}" font-family="sans-serif" font-size="14">{i}. {html.escape(l.name)}</text>'])
    svg.extend(['<text x="30" y="585" font-family="sans-serif" font-size="14">Green: confirmed doorway · Orange: unknown / blocked to routing · Red: confirmed blocked</text>',
                '<text x="30" y="610" font-family="sans-serif" font-size="14">Grey: furniture footprints · Blue dashed: validated sample route · Outside floor polygons: unknown</text>',
                f'<text x="30" y="635" font-family="sans-serif" font-size="14">Coverage: {package.manifest.coverage} · Clearance: 0.30 m · Grid: 0.10 m · Verification: unverified</text>', '</svg>'])
    return "\n".join(svg)+"\n"


def write_fixture(data, output, slug):
    package=add_graph(data)
    payloads={name+".json":json_bytes(getattr(package,name).model_dump(mode="json",by_alias=True)) for name in ["geometry","landmarks","navigation"]}
    payloads["worldmap.archive"]=plistlib.dumps({"format":"touchspace.synthetic-worldmap","version":1,
        "coordinateFrameId":str(package.manifest.coordinate_frame_id),"frameAnchorId":str(package.manifest.frame_anchor_id),
        "relocalizable":False},fmt=plistlib.FMT_BINARY,sort_keys=True)
    package.manifest.checksums={name:hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()}
    payloads["manifest.json"]=json_bytes(package.manifest.model_dump(mode="json",by_alias=True))
    directory=output/slug; directory.mkdir(parents=True,exist_ok=True)
    path=output/(slug+".touchspacemap")
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(payloads.items()):
            entry=zipfile.ZipInfo(name,date_time=(2026,10,25,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED; entry.external_attr=0o100644 << 16
            archive.writestr(entry,raw)
            (directory/name).write_bytes(raw)
    validated=validate_package(path.read_bytes())
    routes=scenarios(validated.map)
    (directory/"route-scenarios.json").write_bytes(json_bytes(routes))
    (output/(slug+".svg")).write_text(preview(validated.map,routes))
    print(f"Created {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {len(package.geometry.rooms)} rooms, {len(package.landmarks.landmarks)} destinations, {len(package.geometry.obstacles)} furniture footprints")
    return validated


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"sample-data/mock-maps")
    parser.add_argument("--seed-catalog",action="store_true",help="Explicitly add the fictional fixtures to the LOCAL public demo catalog")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    packages=[write_fixture(clinic(),args.output,"harbour-clinic"),write_fixture(library(),args.output,"neighbourhood-library")]
    if args.seed_catalog:
        # Import main only on explicit seeding, to load dotenv and the configured local data directory.
        from app.main import get_settings
        from app.touchspace.storage import Catalog
        catalog=Catalog(get_settings().data_dir)
        for package in packages:
            try:
                catalog.save(package,owner="local-synthetic-fixtures",visibility="public")
                print("Seeded local catalog:",package.map.manifest.venue)
            except sqlite3.IntegrityError:
                print("Already in local catalog:",package.map.manifest.venue)


if __name__=="__main__":
    main()
