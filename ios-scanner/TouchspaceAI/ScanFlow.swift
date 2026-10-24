import SwiftUI
import RoomPlan
import ARKit
import AVFoundation
import TouchspaceCore

@MainActor final class ScanCoordinator:NSObject,ObservableObject,@preconcurrency RoomCaptureViewDelegate {
    enum Phase { case ready,capturing,processing,review }
    @Published var phase:Phase = .ready
    @Published var package:MapPackage?
    @Published var error:String?
    @Published var status="Scan one enclosed room in a single uninterrupted session. Slowly capture its floor, walls, doors, and furniture."
    let session=ARSession()
    private let frameId=UUID()
    private var frameAnchor:ARAnchor?
    private var cancelled=false
    private var generation=0
    lazy var captureView:RoomCaptureView = { let v=RoomCaptureView(frame:.zero,arSession:session); v.delegate=self; return v }()
    override init() { super.init() }
    required init?(coder:NSCoder) { super.init() }
    func encode(with coder:NSCoder) {}
    func start() async {
        guard RoomCaptureSession.isSupported else { error="Scanning requires a LiDAR-equipped iPhone or iPad."; return }
        generation += 1; let ticket=generation
        let granted=await AVCaptureDevice.requestAccess(for:.video)
        guard generation==ticket else{return}
        guard granted else { error="Enable camera access in Settings to scan a room."; return }
        error=nil; cancelled=false; phase = .capturing
        captureView.captureSession.run(configuration:RoomCaptureSession.Configuration())
        let anchor=ARAnchor(name:"touchspace-frame:"+frameId.uuidString.lowercased(),transform:matrix_identity_float4x4)
        frameAnchor=anchor; session.add(anchor:anchor)
    }
    func finish() { guard phase == .capturing else{return}; phase = .processing; status="Processing room geometry and saving the same session's world map…"; captureView.captureSession.stop(pauseARSession:false) }
    func cancel() { generation += 1; cancelled=true; captureView.captureSession.stop(); session.pause() }
    func captureView(shouldPresent roomDataForProcessing:CapturedRoomData,error:Error?)->Bool {
        if let error { self.error=error.localizedDescription; phase = .ready; return false }; return !cancelled
    }
    func captureView(didPresent processedResult:CapturedRoom,error:Error?) {
        guard !cancelled else{return}
        if let error { self.error=error.localizedDescription; phase = .ready; return }
        Task { await finalize(processedResult) }
    }
    private func worldData(anchor:ARAnchor) async throws -> Data {
        guard let frame=session.currentFrame, frame.worldMappingStatus == .mapped || frame.worldMappingStatus == .extending,
              case .normal=frame.camera.trackingState else { throw MapError("World mapping is not ready. The result will be saved as a map-only draft. Scan more visual features and retry for live positioning.") }
        guard frame.anchors.contains(where:{$0.identifier==anchor.identifier}) else { throw MapError("The scan's frame anchor was lost. The result will be a map-only draft; a new coherent scan is needed for live positioning.") }
        let map:ARWorldMap=try await withCheckedThrowingContinuation { continuation in
            session.getCurrentWorldMap { map,error in
                if let map { continuation.resume(returning:map) } else { continuation.resume(throwing:error ?? MapError("World map could not be captured.")) }
            }
        }
        guard map.anchors.contains(where:{$0.identifier==anchor.identifier}) else { throw MapError("Captured world map is missing its alignment anchor.") }
        return try NSKeyedArchiver.archivedData(withRootObject:map,requiringSecureCoding:true)
    }
    private func finalize(_ room:CapturedRoom) async {
        do {
            guard let anchor=frameAnchor else { throw MapError("No coherent session anchor is available. Start a new scan.") }
            var world:Data?
            do { world=try await worldData(anchor:anchor) }
            catch { status=error.localizedDescription }
            guard !cancelled else{return}
            var p=try ScanGeometry.make(room:room,frameId:frameId,anchorId:anchor.identifier,world:world)
            if world != nil {
                do { try WorldMapValidator.validate(p) }
                catch { p.worldData=nil; p.manifest.worldMapIncluded=false; status="World data could not be validated. Retaining a map-only draft: "+error.localizedDescription }
            }
            try p.validate(); package=p; phase = .review; session.pause()
        } catch { self.error=error.localizedDescription; phase = .ready; session.pause() }
    }
}

/// RoomPlan floor corners are local plane coordinates; apply the original surface transform.
/// v1 intentionally exports just one coherent room, never aligns independent sessions by guesswork.
enum ScanGeometry {
    static func project(_ local:SIMD3<Float>,_ transform:simd_float4x4)->Point {
        let world=transform*SIMD4<Float>(local.x,local.y,local.z,1)
        return Point(x:Double(world.x),z:Double(world.z))
    }
    static func make(room:CapturedRoom,frameId:UUID,anchorId:UUID,world:Data?) throws -> MapPackage {
        guard room.floors.count==1,let floor=room.floors.first,floor.polygonCorners.count>=3 else { throw MapError("A single complete surveyed floor polygon is required. Rescan one enclosed room, including its floor; unknown floor space cannot become a route.") }
        let polygon=floor.polygonCorners.map{project($0,floor.transform)}
        let roomId=room.identifier.uuidString.lowercased()
        var manifest=Manifest(mapId:"scan-"+UUID().uuidString.lowercased(),title:"Untitled space",floor:"Ground floor",coverage:"One scanned room",contributor:"Volunteer",coordinateFrameId:frameId,frameAnchorId:anchorId,worldMapIncluded:world != nil)
        manifest.verification="unverified"
        var walls=[Wall]()
        let openings=room.doors+room.openings
        for wall in room.walls {
            let length=Double(wall.dimensions.x), a=project(SIMD3(-wall.dimensions.x/2,0,0),wall.transform),b=project(SIMD3(wall.dimensions.x/2,0,0),wall.transform)
            guard length>0.01 else{continue}
            var gaps=[(Double,Double)]()
            for opening in openings where opening.parentIdentifier==wall.identifier {
                let local=simd_inverse(wall.transform)*opening.transform.columns.3
                let center=Double(local.x)+length/2, half=Double(opening.dimensions.x)/2
                gaps.append((max(0,center-half),min(length,center+half)))
            }
            gaps.sort{$0.0<$1.0};var cursor=0.0,index=0
            func at(_ d:Double)->Point { Point(x:a.x+(b.x-a.x)*d/length,z:a.z+(b.z-a.z)*d/length) }
            for (lo,hi) in gaps where hi>lo {
                if lo>cursor { walls.append(Wall(id:"\(wall.identifier.uuidString.lowercased())-\(index)",a:at(cursor),b:at(lo)));index += 1 }
                cursor=max(cursor,hi)
            }
            if cursor<length { walls.append(Wall(id:"\(wall.identifier.uuidString.lowercased())-\(index)",a:at(cursor),b:at(length))) }
        }
        var obstacles=[Obstacle]()
        for object in room.objects {
            let x=object.dimensions.x/2,z=object.dimensions.z/2
            let corners=[SIMD3<Float>(-x,0,-z),SIMD3<Float>(x,0,-z),SIMD3<Float>(x,0,z),SIMD3<Float>(-x,0,z)]
            if x>0.05,z>0.05 { obstacles.append(Obstacle(id:object.identifier.uuidString.lowercased(),polygon:corners.map{project($0,object.transform)})) }
        }
        let raw=try JSONDecoder().decode(JSONValue.self,from:JSONEncoder().encode(room))
        let geometry=Geometry(coordinateFrameId:frameId,rooms:[Room(id:roomId,name:"Scanned room",polygon:polygon)],walls:walls,obstacles:obstacles,capturedRoom:raw)
        let doors=openings.map { surface in Door(id:surface.identifier.uuidString.lowercased(),name:"Doorway",rooms:[roomId],position:project(SIMD3<Float>(0,0,0),surface.transform),width:Double(surface.dimensions.x)) }
        let nav=try GraphBuilder.build(manifest:manifest,geometry:geometry,doors:doors)
        var landmarks=[Landmark]()
        func landmark(id:String,name:String,type:String,p:Point) {
            guard SpatialEngine.contains(p,in:polygon) else{return}
            let nearest=nav.nodes.min{$0.position.distance(to:p)<$1.position.distance(to:p)}
            let node=nearest.flatMap{$0.position.distance(to:p)<=1.5 ? $0.id:nil}
            landmarks.append(Landmark(id:id,name:name,type:type,position:p,roomId:roomId,nodeId:node,provenance:"scan"))
        }
        for (i,d) in doors.enumerated() { landmark(id:d.id,name:"Doorway \(i+1)",type:"other",p:d.position) }
        for (i,o) in room.objects.enumerated() { landmark(id:o.identifier.uuidString.lowercased(),name:"\(String(describing:o.category)) \(i+1)",type:"object",p:project(SIMD3<Float>(0,0,0),o.transform)) }
        // Every scan retains at least one routable labelled waypoint in recorded clear floor space.
        if let first=nav.nodes.first { landmarks.append(Landmark(id:"room-waypoint",name:"Room waypoint",type:"information",position:first.position,roomId:roomId,nodeId:first.id,provenance:"scan")) }
        return MapPackage(manifest:manifest,geometry:geometry,landmarks:Landmarks(coordinateFrameId:frameId,landmarks:landmarks),navigation:nav,worldData:world)
    }
}
struct RoomCapturePreview:UIViewRepresentable {
    @ObservedObject var scanner:ScanCoordinator
    func makeUIView(context:Context)->RoomCaptureView { scanner.captureView }
    func updateUIView(_ view:RoomCaptureView,context:Context) {}
}
struct ScanFlow: View {
    @Environment(\.dismiss) var dismiss
    @Environment(\.scenePhase) var scenePhase
    @EnvironmentObject var library:MapLibrary
    @StateObject var scanner=ScanCoordinator()
    @State private var saved:LocalMap?
    @State private var share=false
    var body:some View {
        NavigationStack {
            Group {
                if !RoomCaptureSession.isSupported {
                    Form { Notice(text:"RoomPlan scanning requires a LiDAR-equipped iPhone or iPad. Import a shared map or try the map-only demo.") }
                } else if scanner.phase == .review, scanner.package != nil {
                    review
                } else {
                    VStack(spacing:16) {
                        Text(scanner.status).padding().accessibilityAddTraits(.isHeader)
                        RoomCapturePreview(scanner:scanner).accessibilityLabel("RoomPlan capture camera. Follow the spoken or visible capture instructions.")
                        if scanner.phase == .processing { ProgressView("Building package…") }
                        if scanner.phase == .ready { Button("Begin scanning") { Task { await scanner.start() } }.buttonStyle(.borderedProminent).tint(.touchspaceButton).foregroundStyle(.white).frame(minHeight:48) }
                        if scanner.phase == .capturing { Button("Finish room scan") { scanner.finish() }.buttonStyle(.borderedProminent).tint(.touchspaceButton).foregroundStyle(.white).frame(minHeight:48) }
                        if let error=scanner.error { Text(error).foregroundStyle(.red).padding() }
                    }
                }
            }.navigationTitle("Scan a space").toolbar { ToolbarItem(placement:.cancellationAction) { Button("Close") { scanner.cancel();dismiss() } } }
                .onChange(of:scenePhase) { _,phase in if phase != .active,scanner.phase != .review { scanner.cancel();scanner.phase = .ready; scanner.error="The scan was interrupted. Begin a new coherent session before saving live world data." } }
                .onDisappear { scanner.cancel() }
                .sheet(isPresented:$share) { if let saved { ShareSheet(items:[saved.url]) } }
        }
    }
    var review:some View {
        Form {
            Section("Name the scan") {
                TextField("Map title",text:Binding(get:{scanner.package!.manifest.title},set:{scanner.package!.manifest.title=$0}))
                TextField("Contributor name",text:Binding(get:{scanner.package!.manifest.contributor},set:{scanner.package!.manifest.contributor=$0}))
                TextField("Floor",text:Binding(get:{scanner.package!.manifest.floor},set:{scanner.package!.manifest.floor=$0}))
                TextField("Room name",text:Binding(get:{scanner.package!.geometry.rooms[0].name},set:{scanner.package!.geometry.rooms[0].name=$0}))
            }
            Section("Landmarks and entrances") {
                ForEach(Array(scanner.package!.landmarks.landmarks.enumerated()),id:\.element.id) { index,lm in
                    VStack(alignment:.leading) {
                        TextField("Landmark name",text:Binding(get:{scanner.package!.landmarks.landmarks[index].name},set:{scanner.package!.landmarks.landmarks[index].name=$0;scanner.package!.landmarks.landmarks[index].provenance="volunteer"}))
                        Picker("Landmark type",selection:Binding(get:{scanner.package!.landmarks.landmarks[index].type},set:{scanner.package!.landmarks.landmarks[index].type=$0;scanner.package!.landmarks.landmarks[index].provenance="volunteer"})) {
                            ForEach(["entrance","exit","information","restroom","object","stairs","elevator","other"],id:\.self){Text($0.capitalized).tag($0)}
                        }
                        if lm.nodeId==nil { Text("No nearby surveyed route waypoint. Map-only landmark.").font(.footnote) }
                    }
                }
            }
            Section("Review connectivity") {
                Text("One scanned room; \(SpatialEngine(package:scanner.package!).componentCount) connected area(s) for navigation.")
                ForEach(Array(scanner.package!.navigation.doors.enumerated()),id:\.element.id) { index,door in
                    VStack(alignment:.leading) {
                        TextField("Doorway name",text:Binding(get:{scanner.package!.navigation.doors[index].name},set:{scanner.package!.navigation.doors[index].name=$0}))
                        Toggle("I checked this doorway was traversable during the scan",isOn:Binding(get:{scanner.package!.navigation.doors[index].traversable},set:{scanner.package!.navigation.doors[index].traversable=$0}))
                    }
                }
                Notice(text:"Single-room MVP: doorways label the boundary; they do not imply that unscanned space beyond them is walkable. Separate scans are never automatically joined.")
                ForEach(scanner.package!.warnings,id:\.self) { Notice(text:$0) }
                if !scanner.status.isEmpty { Text(scanner.status).font(.footnote) }
            }
            Section {
                Button("Save complete package locally") {
                    do {
                        scanner.package!.manifest.updatedAt=ISO8601DateFormatter().string(from:Date())
                        saved=try library.save(scanner.package!);scanner.error=nil
                    } catch { scanner.error=error.localizedDescription }
                }.frame(minHeight:44)
                if let saved {
                    Text("Saved \(saved.package.manifest.title). No data has been uploaded.")
                    Button("Share saved package") { share=true }.frame(minHeight:44)
                    NavigationLink("Open saved map") { MapDetails(map:saved) }
                }
                if let error=scanner.error { Text(error).foregroundStyle(.red) }
            }
        }
    }
}
