import ARKit
import RealityKit
import SwiftUI

/// A geometry-derived 3D model. This never supplies an ARWorldMap or a VerifiedPose.
@MainActor final class VirtualMapScene {
    enum Viewpoint: String, CaseIterable, Identifiable { case overview = "Overview", walk = "First person"; var id:String { rawValue } }
    let package: MapPackage
    let view: ARView
    let model = Entity()
    private let anchor = AnchorEntity(world:.zero)
    private let routeRoot = Entity()
    private let walker = Entity()
    private let camera = PerspectiveCamera()
    private var wallBodies: [Entity] = []
    private var lastRoute: [MapPoint] = []
    private var lastViewpoint: Viewpoint?
    private var fittedSize = CGSize.zero
    private var placedAR = false
    let arPreview: Bool
    let center: MapPoint
    let extent: Double

    init(package:MapPackage,arPreview:Bool = false) throws {
        self.package = package; self.arPreview = arPreview
        let points = package.geometry.rooms.flatMap(\.polygon)
        let minX=points.map(\.x).min() ?? 0,maxX=points.map(\.x).max() ?? 1
        let minZ=points.map(\.z).min() ?? 0,maxZ=points.map(\.z).max() ?? 1
        center = .init(x:(minX+maxX)/2,z:(minZ+maxZ)/2); extent = max(maxX-minX,maxZ-minZ)
        view = ARView(frame:.zero,cameraMode:arPreview ? .ar : .nonAR,automaticallyConfigureSession:false)
        view.accessibilityIdentifier = "virtual-map-scene"
        view.environment.background = arPreview ? .cameraFeed() : .color(UIColor(red:0.88,green:0.92,blue:0.96,alpha:1))
        view.renderOptions = [.disableMotionBlur,.disableDepthOfField]
        let colors: [UIColor] = [.init(red:0.68,green:0.84,blue:0.94,alpha:1),.init(red:0.96,green:0.84,blue:0.66,alpha:1),.init(red:0.73,green:0.88,blue:0.76,alpha:1),.init(red:0.83,green:0.77,blue:0.95,alpha:1),.init(red:0.95,green:0.76,blue:0.77,alpha:1)]
        let floor = Float(package.geometry.floorY)
        for (i,room) in package.geometry.rooms.enumerated() {
            model.addChild(try extrude(room.polygon,bottom:floor-0.035,top:floor,color:colors[i%colors.count]))
        }
        for obstacle in package.geometry.obstacles {
            let tall = obstacle.id.contains("shelf") || obstacle.id.contains("cabinet")
            model.addChild(try extrude(obstacle.polygon,bottom:floor,top:floor+(tall ? 1.6 : 0.75),color:UIColor(red:0.40,green:0.47,blue:0.55,alpha:1)))
        }
        let engine = try SpatialEngine(package)
        for (a,b,thickness) in engine.visibleWallSegments {
            let body = Entity()
            let wall = segment(a,b,y:0.5,width:Float(thickness),height:1,color:UIColor(red:0.18,green:0.24,blue:0.31,alpha:1))
            body.position.y = floor; body.addChild(wall); model.addChild(body); wallBodies.append(body)
        }
        for door in package.navigation.doors {
            let height:Float = door.traversability == "confirmed" ? 0.04 : 0.8
            let marker = segment(door.start,door.end,y:floor+height/2+0.01,width:0.18,height:height,
                color:door.traversability == "confirmed" ? .systemGreen : door.traversability == "blocked" ? .systemRed : .systemOrange)
            model.addChild(marker)
        }
        for landmark in package.landmarks.landmarks {
            let marker = ModelEntity(mesh:.generateBox(size:[0.2,0.06,0.2]),materials:[UnlitMaterial(color:.white)])
            marker.position = [Float(landmark.position.x),floor+0.06,Float(landmark.position.z)]
            model.addChild(marker)
        }
        let cursor = ModelEntity(mesh:.generateSphere(radius:0.12),materials:[UnlitMaterial(color:.systemBlue)])
        cursor.position.y = floor+0.18; walker.addChild(cursor)
        let facing = ModelEntity(mesh:.generateBox(size:[0.06,0.04,0.36]),materials:[UnlitMaterial(color:.systemBlue)])
        facing.position = [0,floor+0.18,-0.19]; walker.addChild(facing)
        model.addChild(walker); model.addChild(routeRoot)
        let light = DirectionalLight(); light.light.intensity = 3500
        light.look(at:[0,0,0],from:[5,12,8],relativeTo:nil); anchor.addChild(light)
        anchor.addChild(model)
        if !arPreview {
            let transform = package.geometry.mapToWorld
            model.position = [Float(transform.x),Float(transform.y),Float(transform.z)]
            model.orientation = simd_quatf(angle:Float(-transform.yaw),axis:[0,1,0])
            camera.camera.fieldOfViewInDegrees = 62; camera.camera.near = 0.02; camera.camera.far = 200
            anchor.addChild(camera); view.scene.addAnchor(anchor)
        }
    }
    private func extrude(_ polygon:[MapPoint],bottom:Float,top:Float,color:UIColor) throws -> ModelEntity {
        let triangles = try PolygonMesh.triangles(polygon)
        var positions: [SIMD3<Float>] = [], normals: [SIMD3<Float>] = [], indices: [UInt32] = []
        func p(_ index:Int,_ y:Float) -> SIMD3<Float> { [Float(polygon[index].x),y,Float(polygon[index].z)] }
        func face(_ a:SIMD3<Float>,_ b:SIMD3<Float>,_ c:SIMD3<Float>) {
            let n = simd_normalize(simd_cross(b-a,c-a)), start = UInt32(positions.count)
            positions += [a,b,c]; normals += [n,n,n]; indices += [start,start+1,start+2]
        }
        for i in stride(from:0,to:triangles.count,by:3) {
            let a=Int(triangles[i]),b=Int(triangles[i+1]),c=Int(triangles[i+2])
            face(p(a,top),p(c,top),p(b,top)); face(p(a,bottom),p(b,bottom),p(c,bottom))
        }
        let signed = polygon.indices.reduce(0.0) { $0+polygon[$1].x*polygon[($1+1)%polygon.count].z-polygon[($1+1)%polygon.count].x*polygon[$1].z }
        for i in polygon.indices {
            let j=(i+1)%polygon.count
            if signed >= 0 { face(p(i,bottom),p(j,top),p(i,top)); face(p(i,bottom),p(j,bottom),p(j,top)) }
            else { face(p(i,bottom),p(i,top),p(j,top)); face(p(i,bottom),p(j,top),p(j,bottom)) }
        }
        var descriptor = MeshDescriptor(name:"map-polygon")
        descriptor.positions = MeshBuffers.Positions(positions); descriptor.normals = MeshBuffers.Normals(normals); descriptor.primitives = .triangles(indices)
        return ModelEntity(mesh:try MeshResource.generate(from:[descriptor]),materials:[SimpleMaterial(color:color,roughness:1,isMetallic:false)])
    }
    private func segment(_ a:MapPoint,_ b:MapPoint,y:Float,width:Float,height:Float,color:UIColor) -> ModelEntity {
        let length = Float(a.distance(to:b))
        let entity = ModelEntity(mesh:.generateBox(size:[width,height,max(0.001,length)]),materials:[SimpleMaterial(color:color,roughness:1,isMetallic:false)])
        entity.position = [Float((a.x+b.x)/2),y,Float((a.z+b.z)/2)]
        entity.orientation = simd_quatf(angle:Float(atan2(b.x-a.x,b.z-a.z)),axis:[0,1,0])
        return entity
    }
    func update(pose:SimulatedPose,route:PlannedRoute?,viewpoint:Viewpoint) {
        if (route?.waypoints ?? []) != lastRoute {
            for child in Array(routeRoot.children) { child.removeFromParent() }
            lastRoute = route?.waypoints ?? []
            let floor = Float(package.geometry.floorY)
            for (a,b) in zip(lastRoute,lastRoute.dropFirst()) {
                routeRoot.addChild(segment(a,b,y:floor+0.06,width:0.11,height:0.035,color:.systemYellow))
            }
            if let destination = lastRoute.last {
                let marker = ModelEntity(mesh:.generateBox(size:[0.25,0.6,0.25]),materials:[UnlitMaterial(color:.systemGreen)])
                marker.position = [Float(destination.x),floor+0.3,Float(destination.z)]; routeRoot.addChild(marker)
            }
        }
        walker.position.x = Float(pose.position.x); walker.position.z = Float(pose.position.z)
        walker.orientation = simd_quatf(angle:Float(-pose.heading),axis:[0,1,0])
        walker.isEnabled = viewpoint == .overview || arPreview
        let height:Float = viewpoint == .overview || arPreview ? 0.65 : 2.4
        for body in wallBodies { body.scale.y = height }
        guard !arPreview else { return }
        let t = package.geometry.mapToWorld
        if viewpoint == .walk {
            let p = t.world(pose.position)
            camera.position = [Float(p.x),Float(package.geometry.floorY+t.y+1.55),Float(p.z)]
            camera.orientation = simd_quatf(angle:Float(-(pose.heading+t.yaw)),axis:[0,1,0])*simd_quatf(angle:-.pi/8,axis:[1,0,0])
        } else if lastViewpoint != .overview || fittedSize != view.bounds.size {
            fitOverview()
        }
        lastViewpoint = viewpoint
    }
    func fitOverview() {
        guard !arPreview, view.bounds.width > 0, view.bounds.height > 0 else { return }
        let t = package.geometry.mapToWorld, c = t.world(center)
        let y = Float(package.geometry.floorY+t.y), target:SIMD3<Float> = [Float(c.x),y,Float(c.z)]
        let direction = simd_normalize(SIMD3<Float>(0.45,0.9,0.7))
        let tanV = tan(camera.camera.fieldOfViewInDegrees*Float.pi/360)
        let tanH = tanV*Float(view.bounds.width/view.bounds.height)
        let corners = package.geometry.rooms.flatMap(\.polygon).flatMap { p -> [SIMD4<Float>] in
            let world = t.world(p)
            return [[Float(world.x),y-0.05,Float(world.z),1],[Float(world.x),y+1.6,Float(world.z),1]]
        }
        var distance = Float(max(3,extent))*0.65
        for _ in 0..<40 {
            camera.look(at:target,from:target+direction*distance,relativeTo:nil)
            let inverse = simd_inverse(camera.transform.matrix)
            let fits = corners.allSatisfy { p in
                let eye = inverse*p, depth = -eye.z
                return depth > 0.1 && abs(eye.x) < depth*tanH*0.88 && abs(eye.y) < depth*tanV*0.88
            }
            if fits { break }
            distance *= 1.06
        }
        fittedSize = view.bounds.size
    }
    func startAR() {
        guard arPreview, ARWorldTrackingConfiguration.isSupported else { return }
        placedAR = false; view.scene.anchors.removeAll()
        let config = ARWorldTrackingConfiguration()
        view.session.run(config,options:[.resetTracking,.removeExistingAnchors])
    }
    @discardableResult func placeAR() -> Bool {
        guard arPreview, let frame = view.session.currentFrame, case .normal = frame.camera.trackingState else { return false }
        anchor.removeFromParent()
        var offset = matrix_identity_float4x4; offset.columns.3 = [0,-0.35,-1.0,1]
        anchor.transform.matrix = frame.camera.transform*offset
        model.scale = .init(repeating:Float(0.75/max(1,extent)))
        model.position = [-Float(center.x)*model.scale.x,-Float(package.geometry.floorY)*model.scale.y,-Float(center.z)*model.scale.z]
        model.orientation = .init(angle:0,axis:[0,1,0])
        view.scene.addAnchor(anchor); placedAR = true
        return true
    }
    func stop() { if arPreview { view.session.pause() } }
}

struct VirtualMapView: UIViewRepresentable {
    let scene: VirtualMapScene
    let pose: SimulatedPose
    let route: PlannedRoute?
    let viewpoint: VirtualMapScene.Viewpoint
    func makeUIView(context:Context) -> ARView { scene.update(pose:pose,route:route,viewpoint:viewpoint); if viewpoint == .overview { DispatchQueue.main.async { scene.fitOverview() } }; return scene.view }
    func updateUIView(_ view:ARView,context:Context) { scene.update(pose:pose,route:route,viewpoint:viewpoint); if viewpoint == .overview { DispatchQueue.main.async { scene.fitOverview() } } }
}
