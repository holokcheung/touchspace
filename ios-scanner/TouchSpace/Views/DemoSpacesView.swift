import SwiftUI

struct DemoSpacesView: View {
    let maps: [MapPackage]
    let api: APIClient?

    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Text("Choose a space to explore").font(.title2.bold())
                Text("These virtual spaces work offline. Play a route or move around using the walkthrough controls.")
                    .foregroundStyle(.secondary)
                ForEach(maps) { map in
                    let name = map.manifest.venue.replacingOccurrences(of:" (Synthetic)",with:"")
                    VStack(alignment:.leading,spacing:14) {
                        Text(name).font(.headline)
                        Text("\(map.geometry.rooms.count) rooms · \(map.landmarks.landmarks.count) destinations")
                            .font(.subheadline).foregroundStyle(.secondary)
                        FloorPlanView(package:map,showLandmarkLabels:false).frame(height:190)
                        NavigationLink {
                            SimulationEntry(package:map)
                        } label: {
                            Label("Start 3D walkthrough",systemImage:"figure.walk")
                                .frame(maxWidth:.infinity,minHeight:32)
                        }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .accessibilityLabel("Start 3D walkthrough of \(name)")
                        NavigationLink {
                            MapExplorerView(package:map,api:api)
                        } label: {
                            Label("Explore floor plan",systemImage:"map")
                                .frame(maxWidth:.infinity,minHeight:32)
                        }
                        .buttonStyle(.bordered).controlSize(.large)
                        .accessibilityLabel("Explore map of \(name)")
                    }
                    .padding().frame(maxWidth:.infinity,alignment:.leading)
                    .background(.quaternary.opacity(0.4),in:RoundedRectangle(cornerRadius:18))
                }
                Text("Simulation uses virtual positions. Camera-based AR model preview is available on supported physical devices.")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding()
        }
        .navigationTitle("Demo spaces")
        .navigationBarTitleDisplayMode(.inline)
    }
}
