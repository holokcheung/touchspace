import SwiftUI

struct FloorPlanView: View {
    let package: MapPackage
    var route: PlannedRoute?
    var pose: MapPoint?
    var heading: Double?
    var selected: MapPoint?
    var showLandmarkLabels = true
    var onSelect: ((MapPoint) -> Void)?
    private var bounds: (Double,Double,Double,Double) {
        let points = package.geometry.rooms.flatMap(\.polygon)
        return (points.map(\.x).min() ?? 0,points.map(\.z).min() ?? 0,points.map(\.x).max() ?? 1,points.map(\.z).max() ?? 1)
    }
    var body: some View {
        GeometryReader { geometry in
            let b = bounds
            let scale = min((geometry.size.width-32)/max(1,b.2-b.0),(geometry.size.height-32)/max(1,b.3-b.1))
            let ox = (geometry.size.width-(b.2-b.0)*scale)/2, oy = (geometry.size.height-(b.3-b.1)*scale)/2
            Canvas { context,size in
                func point(_ p:MapPoint) -> CGPoint { CGPoint(x:(p.x-b.0)*scale+ox,y:(p.z-b.1)*scale+oy) }
                func polygon(_ points:[MapPoint]) -> Path {
                    Path { path in guard let first=points.first else { return }; path.move(to:point(first)); for p in points.dropFirst() { path.addLine(to:point(p)) }; path.closeSubpath() }
                }
                for room in package.geometry.rooms {
                    context.fill(polygon(room.polygon),with:.color(Color.touchSpaceMint.opacity(0.12)))
                    context.stroke(polygon(room.polygon),with:.color(.secondary),lineWidth:1)
                }
                for item in package.geometry.obstacles { context.fill(polygon(item.polygon),with:.color(.secondary.opacity(0.5))) }
                for wall in package.geometry.walls {
                    context.stroke(Path { $0.move(to:point(wall.start)); $0.addLine(to:point(wall.end)) },with:.color(.primary),lineWidth:max(2,wall.thickness*scale))
                }
                for door in package.navigation.doors {
                    context.stroke(Path { $0.move(to:point(door.start)); $0.addLine(to:point(door.end)) },with:.color(door.traversability == "confirmed" ? .green : .orange),lineWidth:5)
                }
                if let route {
                    context.stroke(Path { path in for (i,p) in route.waypoints.enumerated() { if i==0 { path.move(to:point(p)) } else { path.addLine(to:point(p)) } } },with:.color(.touchSpaceMint),style:.init(lineWidth:4,lineCap:.round,lineJoin:.round))
                }
                for landmark in package.landmarks.landmarks {
                    let p = point(landmark.position)
                    context.fill(Path(ellipseIn:CGRect(x:p.x-4,y:p.y-4,width:8,height:8)),with:.color(.green))
                    if showLandmarkLabels {
                        context.draw(Text(landmark.name).font(.caption).foregroundStyle(.primary),at:CGPoint(x:p.x,y:p.y+14))
                    }
                }
                if let pose, let heading {
                    let origin = point(pose), target = CGPoint(x:origin.x+sin(heading)*20,y:origin.y-cos(heading)*20)
                    context.stroke(Path { $0.move(to:origin); $0.addLine(to:target) },with:.color(.touchSpaceMint),style:.init(lineWidth:4,lineCap:.round))
                }
                for p in [pose,selected].compactMap({ $0 }) {
                    let p = point(p)
                    context.fill(Path(ellipseIn:CGRect(x:p.x-7,y:p.y-7,width:14,height:14)),with:.color(.touchSpaceMint))
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { location in
                onSelect?(.init(x:(location.x-ox)/scale+b.0,z:(location.y-oy)/scale+b.1))
            }
        }
        .frame(minHeight:180)
        .accessibilityElement(children:.ignore)
        .accessibilityLabel("Floor plan. \(package.geometry.rooms.count) scanned areas, \(package.landmarks.landmarks.count) named destinations. Unknown areas and unconfirmed doors are blocked.")
    }
}
