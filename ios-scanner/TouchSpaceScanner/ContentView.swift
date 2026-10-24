import RoomPlan
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: ScanStore
    @State private var scanning = false
    @State private var openedScan: SavedScan?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Scan a room with LiDAR. TouchSpace turns it into a 3D-printable tactile map.")
                        if !RoomCaptureSession.isSupported {
                            Label("This device can't run RoomPlan. You need an iPhone or iPad with a LiDAR Scanner (for example iPhone 12 Pro or later Pro models).",
                                  systemImage: "exclamationmark.triangle")
                                .foregroundStyle(.orange)
                        }
                    }
                    .padding(.vertical, 4)

                    Button {
                        scanning = true
                    } label: {
                        Label("Start a new scan", systemImage: "viewfinder")
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!RoomCaptureSession.isSupported)
                    .accessibilityHint("Opens the camera to scan the walls, doors and furniture of one room.")
                }

                Section("Saved scans") {
                    if store.scans.isEmpty {
                        Text("No scans yet.").foregroundStyle(.secondary)
                    }
                    ForEach(store.scans) { scan in
                        NavigationLink(value: scan) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(scan.name).font(.headline)
                                Text(scan.createdAt.formatted(date: .abbreviated, time: .shortened))
                                    .font(.subheadline).foregroundStyle(.secondary)
                                Text(scan.summary).font(.footnote).foregroundStyle(.secondary)
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                    .onDelete { offsets in
                        offsets.map { store.scans[$0] }.forEach(store.delete)
                    }
                }
            }
            .navigationTitle("TouchSpace Scanner")
            .navigationDestination(for: SavedScan.self) { scan in
                ScanDetailView(scan: scan)
            }
            .navigationDestination(item: $openedScan) { scan in
                ScanDetailView(scan: scan)
            }
            .fullScreenCover(isPresented: $scanning) {
                ScanFlowView { saved in
                    scanning = false
                    openedScan = saved
                }
            }
        }
    }
}
