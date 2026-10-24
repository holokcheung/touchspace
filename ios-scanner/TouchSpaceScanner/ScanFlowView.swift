import RoomPlan
import SwiftUI

/// Full-screen scanning flow: scan, stop, let RoomPlan process, then name and save the result.
struct ScanFlowView: View {
    enum Phase: Equatable {
        case scanning
        case processing
        case review
        case failed(String)
    }

    @EnvironmentObject private var store: ScanStore
    @Environment(\.dismiss) private var dismiss
    let onSaved: (SavedScan) -> Void

    @State private var controller: RoomCaptureViewController?
    @State private var phase: Phase = .scanning
    @State private var result: CapturedRoom?
    @State private var instruction: String?
    @State private var name = "Room"
    @State private var saveError: String?

    var body: some View {
        ZStack {
            RoomCaptureRepresentable(
                controller: $controller,
                onProcessed: { room in
                    result = room
                    phase = .review
                    UIAccessibility.post(notification: .announcement,
                                         argument: "Scan processed. \(room.walls.count) walls and \(room.doors.count) doors found.")
                },
                onFailed: { error in phase = .failed(error.localizedDescription) },
                onInstruction: { instr in
                    let message = instr.message
                    if message != instruction, let message {
                        UIAccessibility.post(notification: .announcement, argument: message)
                    }
                    instruction = message
                }
            )
            .ignoresSafeArea()
            .accessibilityLabel("Camera view of the room being scanned")

            VStack {
                topBar
                Spacer()
                if let instruction, phase == .scanning {
                    Text(instruction)
                        .font(.headline)
                        .padding(12)
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
                        .padding(.bottom, 12)
                }
                bottomPanel
            }
            .padding()
        }
    }

    private var topBar: some View {
        HStack {
            Button("Cancel", role: .cancel) {
                controller?.stopScanning()
                dismiss()
            }
            .buttonStyle(.bordered)
            Spacer()
            if phase == .scanning {
                Button("Done") {
                    phase = .processing
                    controller?.stopScanning()
                }
                .buttonStyle(.borderedProminent)
                .accessibilityHint("Stops scanning and builds the room model.")
            }
        }
    }

    @ViewBuilder private var bottomPanel: some View {
        switch phase {
        case .scanning:
            Text("Walk slowly around the room. Point the camera at every wall, door and opening.")
                .font(.subheadline)
                .multilineTextAlignment(.center)
                .padding(12)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        case .processing:
            ProgressView("Building the room model…")
                .padding(16)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
        case .review:
            if let result {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Found \(result.walls.count) walls, \(result.doors.count) doors, \(result.openings.count) openings, \(result.windows.count) windows and \(result.objects.count) objects.")
                    TextField("Scan name", text: $name)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel("Scan name")
                    if let saveError {
                        Text(saveError).foregroundStyle(.red)
                    }
                    Button {
                        do {
                            let saved = try store.save(result, name: name.isEmpty ? "Room" : name)
                            onSaved(saved)
                        } catch {
                            saveError = "Could not save the scan: \(error.localizedDescription)"
                        }
                    } label: {
                        Text("Save scan").frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding(16)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }
        case .failed(let message):
            VStack(spacing: 12) {
                Text("The scan could not be completed.").font(.headline)
                Text(message).font(.subheadline)
                Button("Close") { dismiss() }.buttonStyle(.borderedProminent)
            }
            .padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        }
    }
}
