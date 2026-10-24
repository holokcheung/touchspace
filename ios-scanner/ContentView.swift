import RoomPlan
import SwiftUI

struct ContentView: View {
    @StateObject private var scanner = RoomScanner()

    var body: some View {
        NavigationStack {
            VStack(spacing: 18) {
                ZStack(alignment: .topLeading) {
                    RoomCaptureSurface(scanner: scanner)
                        .clipShape(RoundedRectangle(cornerRadius: 18))
                        .accessibilityLabel("Live RoomPlan scanning view")
                    if scanner.isScanning {
                        Label("Move slowly around the room", systemImage: "viewfinder")
                            .font(.caption.weight(.semibold))
                            .padding(10)
                            .background(.regularMaterial, in: Capsule())
                            .padding(12)
                    } else {
                        VStack(spacing: 14) {
                            Label("Scan a room", systemImage: "view.3d")
                                .font(.title2.weight(.semibold))
                            Text("The scan identifies room surfaces and furniture. Finish the scan to export a RoomPlan JSON file.")
                                .multilineTextAlignment(.center)
                                .foregroundStyle(.secondary)
                            Button(action: scanner.start) {
                                Label("Start scan", systemImage: "viewfinder")
                            }
                                .buttonStyle(.borderedProminent)
                                .tint(.green)
                        }
                        .padding()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(.regularMaterial)
                    }
                }
                .frame(maxHeight: .infinity)

                if let message = scanner.message {
                    Text(message)
                        .font(.footnote)
                        .foregroundStyle(scanner.error == nil ? .secondary : .red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                if scanner.isScanning {
                    Button("Finish scan", systemImage: "checkmark.circle.fill", action: scanner.stop)
                        .buttonStyle(.borderedProminent)
                        .tint(.green)
                        .frame(maxWidth: .infinity)
                }

                if !scanner.exportURLs.isEmpty {
                    ShareLink(items: scanner.exportURLs) {
                        Label("Share JSON and USDZ", systemImage: "square.and.arrow.up")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
            }
            .padding()
            .navigationTitle("TouchSpace Scan")
            .toolbar {
                if !scanner.exportURLs.isEmpty {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button("New scan", systemImage: "arrow.counterclockwise") { scanner.reset() }
                    }
                }
            }
        }
        .tint(Color(red: 0.22, green: 0.48, blue: 0.39))
    }
}

@MainActor
final class RoomScanner: NSObject, ObservableObject, RoomCaptureViewDelegate {
    @Published var isScanning = false
    @Published var message: String?
    @Published var exportURLs: [URL] = []
    @Published var error: Error?

    private weak var captureView: RoomCaptureView?
    private var capturedRoom: CapturedRoom?
    private var sessionRunning = false

    func attach(_ view: RoomCaptureView) {
        captureView = view
        view.delegate = self
        if isScanning && !sessionRunning {
            runSession(in: view)
        }
    }

    func start() {
        guard RoomCaptureSession.isSupported else {
            message = "RoomPlan is not supported on this device."
            return
        }
        isScanning = true
        message = "Scanning. Walk around the room and include doorways in view."
        error = nil
        if let captureView, !sessionRunning {
            runSession(in: captureView)
        }
    }

    func stop() {
        captureView?.captureSession.stop(pauseARSession: false)
        sessionRunning = false
        isScanning = false
        message = "Processing the scan…"
    }

    private func runSession(in view: RoomCaptureView) {
        let configuration = RoomCaptureSession.Configuration()
        view.captureSession.run(configuration: configuration)
        sessionRunning = true
    }

    func reset() {
        exportURLs = []
        capturedRoom = nil
        sessionRunning = false
        error = nil
        message = nil
    }

    func captureView(shouldPresent room: CapturedRoom, error: Error?) -> Bool {
        if let error {
            self.error = error
            message = "RoomPlan could not finish this scan: \(error.localizedDescription)"
            return false
        }
        capturedRoom = room
        return true
    }

    func captureView(didPresent room: CapturedRoom, error: Error?) {
        guard let error else {
            save(room)
            return
        }
        self.error = error
        message = "RoomPlan preview error: \(error.localizedDescription)"
    }

    private func save(_ room: CapturedRoom) {
        do {
            let folder = FileManager.default.temporaryDirectory
                .appendingPathComponent("TouchSpace-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)

            let jsonURL = folder.appendingPathComponent("RoomPlan.json")
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(room).write(to: jsonURL, options: .atomic)

            let usdzURL = folder.appendingPathComponent("RoomPlan.usdz")
            var files = [jsonURL]
            do {
                try room.export(to: usdzURL)
                files.append(usdzURL)
            } catch {
                // The structured JSON remains useful even if mesh export fails.
                message = "JSON saved. USDZ export was unavailable: \(error.localizedDescription)"
            }
            exportURLs = files
            if message == "Processing the scan…" {
                message = "RoomPlan JSON is ready to share with TouchSpace AI."
            }
            self.error = nil
        } catch {
            self.error = error
            message = "Could not save the RoomPlan JSON: \(error.localizedDescription)"
        }
    }
}

private struct RoomCaptureSurface: UIViewRepresentable {
    @ObservedObject var scanner: RoomScanner

    func makeUIView(context: Context) -> RoomCaptureView {
        let view = RoomCaptureView(frame: .zero)
        scanner.attach(view)
        return view
    }

    func updateUIView(_ uiView: RoomCaptureView, context: Context) {
        scanner.attach(uiView)
    }
}
