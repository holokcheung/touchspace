import Combine
import Foundation
import simd
#if canImport(RoomPlan)
import RoomPlan
#endif

/// Streams the scan and the phone's position to a Mac running `python -m app.live` (backend/),
/// which draws them on a DotPad. Off until a ws:// or wss:// URL is saved in Settings.
/// Protocol: docs/live-dotpad.md. Nothing here affects scanning or guidance if the Mac is absent.
@MainActor final class DotPadLink: ObservableObject {
    static let shared = DotPadLink()
    static let urlKey = "dotpadLinkURL"

    enum State: Equatable { case off, connecting, connected, failed(String) }
    @Published private(set) var state = State.off
    /// What the Mac last reported, e.g. "DotPad connected · 120 frames".
    @Published private(set) var detail = ""

    private let session = URLSession(configuration:.default)
    private var task: URLSessionWebSocketTask?
    private var url: URL?
    private var generation = 0
    private var lastMap: String?
    private var lastPoseAt = 0.0
    private var pendingPose: String?
    private var poseFlush: Task<Void,Never>?
    private var roomFlush: Task<Void,Never>?
    private var lastRoomAt = 0.0
    private var poseTimer: Timer?
    private static let poseInterval = 0.1
    private static let roomInterval = 1.0

    private init() {
        if let saved = UserDefaults.standard.string(forKey:Self.urlKey) { url = Self.validURL(saved) }
    }

    static func validURL(_ text: String) -> URL? {
        guard let url = URL(string:text.trimmingCharacters(in:.whitespaces)), ["ws","wss"].contains(url.scheme), url.host != nil else { return nil }
        return url
    }

    /// Save a URL ("" turns the link off) and reconnect.
    func configure(_ text: String) {
        let trimmed = text.trimmingCharacters(in:.whitespaces)
        UserDefaults.standard.set(trimmed, forKey:Self.urlKey)
        url = Self.validURL(trimmed)
        disconnect()
        if url != nil { connect() }
    }

    var configuredURL: String { UserDefaults.standard.string(forKey:Self.urlKey) ?? "" }

    /// Connect now if an address is saved (otherwise the first scan or pose connects).
    func wake() { if url != nil, task == nil { connect() } }

    // MARK: Live scan (ARKit world frame, as RoomPlan reports it)

    #if canImport(RoomPlan)
    /// Rooms finished earlier in this AR session plus the one being scanned. Sent at most once a
    /// second; the newest version always goes out.
    func sendRooms(_ rooms: [CapturedRoom], force: Bool = false) {
        guard url != nil, !rooms.isEmpty else { return }
        roomFlush?.cancel()
        let wait = force ? 0 : max(0, Self.roomInterval-(now-lastRoomAt))
        roomFlush = Task { [weak self] in
            if wait > 0 { try? await Task.sleep(nanoseconds:UInt64(wait*1e9)) }
            guard !Task.isCancelled, let self else { return }
            guard let data = try? JSONEncoder().encode(rooms), let json = String(data:data,encoding:.utf8) else { return }
            self.lastRoomAt = self.now
            self.sendMap("{\"type\":\"map\",\"live\":true,\"name\":\"Live scan\",\"room\":{\"rooms\":\(json)}}")
        }
    }
    #endif

    /// Send the camera pose about ten times a second while `source` returns one.
    func followWorldPose(_ source: @escaping @MainActor () -> simd_float4x4?) {
        poseTimer?.invalidate()
        poseTimer = Timer.scheduledTimer(withTimeInterval:Self.poseInterval,repeats:true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if let transform = source() { self.sendWorldPose(transform) } else { self.sendNoPose() }
            }
        }
    }

    func stopFollowingPose() { poseTimer?.invalidate(); poseTimer = nil; sendNoPose() }

    func sendWorldPose(_ t: simd_float4x4) {
        let c = [t.columns.0,t.columns.1,t.columns.2,t.columns.3].flatMap { [$0.x,$0.y,$0.z,$0.w] }
        guard c.allSatisfy({ $0.isFinite }) else { return }
        sendPose("{\"type\":\"pose\",\"frame\":\"world\",\"transform\":[\(c.map { String($0) }.joined(separator:","))]}")
    }

    // MARK: Saved maps (map frame: MapPoint x/z, heading clockwise from -Z)

    func sendMap(_ package: MapPackage) {
        guard url != nil else { return }
        struct Message: Encodable { let type: String; let name: String; let geometry: MapGeometry; let doors: [MapDoor] }
        let message = Message(type:"map",name:package.manifest.venue,geometry:package.geometry,doors:package.navigation.doors)
        guard let data = try? JSONEncoder().encode(message), let json = String(data:data,encoding:.utf8) else { return }
        sendMap(json)
    }

    func sendMapPose(_ position: MapPoint, heading: Double) {
        guard position.x.isFinite, position.z.isFinite, heading.isFinite else { return }
        sendPose("{\"type\":\"pose\",\"frame\":\"map\",\"x\":\(position.x),\"z\":\(position.z),\"heading\":\(heading)}")
    }

    /// Tracking lost or guidance stopped: the X leaves the DotPad.
    func sendNoPose() {
        poseFlush?.cancel(); poseFlush = nil; pendingPose = nil
        guard lastPoseAt != 0 else { return }
        lastPoseAt = 0
        send("{\"type\":\"pose\",\"frame\":\"none\"}")
    }

    // MARK: Connection

    private var now: Double { ProcessInfo.processInfo.systemUptime }

    /// At most ten poses a second, and the latest one always goes out (a single step in the
    /// simulation must still move the X).
    private func sendPose(_ text: String) {
        guard url != nil else { return }
        let wait = Self.poseInterval-(now-lastPoseAt)
        if wait <= 0 {
            poseFlush?.cancel(); poseFlush = nil; pendingPose = nil
            lastPoseAt = now; send(text); return
        }
        pendingPose = text
        guard poseFlush == nil else { return }
        poseFlush = Task { [weak self] in
            try? await Task.sleep(nanoseconds:UInt64(wait*1e9))
            guard !Task.isCancelled, let self, let text = self.pendingPose else { return }
            self.poseFlush = nil; self.pendingPose = nil
            self.lastPoseAt = self.now; self.send(text)
        }
    }

    private func sendMap(_ json: String) {
        lastMap = json  // resent after a reconnect
        send(json)
    }

    private func send(_ text: String) {
        guard url != nil else { return }
        if task == nil { connect() }
        guard state == .connected, let task else { return }
        task.send(.string(text)) { [weak self] error in
            guard let error else { return }
            Task { @MainActor in self?.dropped(error.localizedDescription) }
        }
    }

    private func connect() {
        guard let url, task == nil else { return }
        generation += 1
        var request = URLRequest(url:url)
        request.setValue("1",forHTTPHeaderField:"ngrok-skip-browser-warning")
        let task = session.webSocketTask(with:request)
        task.maximumMessageSize = 1 << 20
        self.task = task
        state = .connecting; detail = "Connecting to \(url.host ?? "Mac")…"
        task.resume()
        task.send(.string("{\"type\":\"hello\",\"client\":\"TouchSpace iOS\"}")) { _ in }
        receive(task, generation:generation)
    }

    private func receive(_ task: URLSessionWebSocketTask, generation: Int) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, generation == self.generation else { return }
                switch result {
                case .failure(let error): self.dropped(error.localizedDescription)
                case .success(let message):
                    if case .string(let text) = message { self.handle(text) }
                    self.receive(task, generation:generation)
                }
            }
        }
    }

    private func handle(_ text: String) {
        guard let object = try? JSONSerialization.jsonObject(with:Data(text.utf8)) as? [String:Any] else { return }
        if object["type"] as? String == "status" {
            let first = state != .connected
            state = .connected
            let pad = object["dotpad"] as? String == "connected" ? "DotPad connected" : "Waiting for the DotPad on the Mac"
            detail = "\(pad) · \(object["frames_sent"] as? Int ?? 0) frames"
            if first, let lastMap { send(lastMap) }
        } else if object["type"] as? String == "error" {
            detail = "Mac could not use a message: \(object["message"] as? String ?? "unknown")"
        }
    }

    private func dropped(_ reason: String) {
        task?.cancel(with:.goingAway,reason:nil); task = nil
        generation += 1
        guard url != nil else { state = .off; return }
        state = .failed(reason); detail = "Not connected: \(reason). Retrying…"
        let expected = generation
        Task { [weak self] in
            try? await Task.sleep(nanoseconds:2_000_000_000)
            guard let self, self.generation == expected, self.task == nil else { return }
            self.connect()
        }
    }

    private func disconnect() {
        generation += 1
        task?.cancel(with:.goingAway,reason:nil); task = nil
        state = url == nil ? .off : .connecting
        detail = ""
    }
}
