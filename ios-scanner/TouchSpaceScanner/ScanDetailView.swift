import QuickLook
import SwiftUI

struct ScanDetailView: View {
    @EnvironmentObject private var store: ScanStore
    let scan: SavedScan

    @AppStorage("touchspaceServer") private var server = "http://192.168.1.20:8000"
    @State private var name = ""
    @State private var previewURL: URL?
    @State private var uploading = false
    @State private var uploadMessage: String?
    @State private var uploadFailed = false

    private var current: SavedScan { store.scans.first { $0.id == scan.id } ?? scan }

    var body: some View {
        Form {
            Section("Scan") {
                TextField("Name", text: $name)
                    .onSubmit { store.rename(current, to: name) }
                    .accessibilityLabel("Scan name")
                LabeledContent("Captured", value: current.createdAt.formatted(date: .abbreviated, time: .shortened))
                LabeledContent("Walls", value: "\(current.walls)")
                LabeledContent("Doors", value: "\(current.doors)")
                LabeledContent("Openings", value: "\(current.openings)")
                LabeledContent("Windows", value: "\(current.windows)")
                LabeledContent("Objects", value: "\(current.objects)")
            }

            Section {
                ShareLink(item: store.jsonURL(for: current)) {
                    Label("Share RoomPlan JSON", systemImage: "square.and.arrow.up")
                }
                if let usdz = store.usdzURL(for: current) {
                    ShareLink(item: usdz) {
                        Label("Share 3D model (USDZ)", systemImage: "cube")
                    }
                    Button {
                        previewURL = usdz
                    } label: {
                        Label("Preview 3D model", systemImage: "eye")
                    }
                }
            } header: {
                Text("Export")
            } footer: {
                Text("Upload the JSON file on the TouchSpace website (Upload scan page), or send it straight to your computer below.")
            }

            Section {
                TextField("Server address", text: $server)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityLabel("TouchSpace server address")
                Button {
                    Task { await upload() }
                } label: {
                    if uploading {
                        ProgressView()
                    } else {
                        Label("Send to TouchSpace", systemImage: "paperplane")
                    }
                }
                .disabled(uploading)
                if let uploadMessage {
                    Text(uploadMessage)
                        .foregroundStyle(uploadFailed ? .red : .primary)
                        .accessibilityAddTraits(.updatesFrequently)
                }
            } header: {
                Text("Send to computer")
            } footer: {
                Text("Run the TouchSpace backend on your computer with --host 0.0.0.0 and enter its address on the same Wi-Fi network, e.g. http://192.168.1.20:8000.")
            }
        }
        .navigationTitle(current.name)
        .onAppear { name = current.name }
        .onDisappear { if name != current.name { store.rename(current, to: name) } }
        .quickLookPreview($previewURL)
    }

    private func upload() async {
        uploading = true
        uploadMessage = nil
        defer { uploading = false }
        do {
            let result = try await Uploader.upload(fileURL: store.jsonURL(for: current), displayName: current.name, server: server)
            uploadFailed = false
            var text = "Uploaded as “\(result.mapName)”. Open TouchSpace on your computer and choose it under Your maps."
            if !result.warnings.isEmpty {
                text += "\n\nNotes:\n• " + result.warnings.prefix(4).joined(separator: "\n• ")
            }
            uploadMessage = text
        } catch {
            uploadFailed = true
            uploadMessage = error.localizedDescription
        }
        UIAccessibility.post(notification: .announcement, argument: uploadMessage ?? "")
    }
}
