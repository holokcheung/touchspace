import SwiftUI

struct DemoSpacesView: View {
    let maps: [MapPackage]
    let api: APIClient?

    var body: some View {
        ScrollView {
            VStack(alignment:.leading,spacing:20) {
                Text("Choose a space to explore").font(.title2.bold())
                Text("Step into a space in first person. Swipe to look, use the chevrons to move, and hold the microphone to ask a question.")
                    .foregroundStyle(.secondary)
                ForEach(maps) { map in
                    let name = map.manifest.venue.replacingOccurrences(of:" (Synthetic)",with:"")
                    VStack(alignment:.leading,spacing:14) {
                        Text(name).font(.headline)
                        Text("\(map.geometry.rooms.count) rooms · \(map.landmarks.landmarks.count) destinations")
                            .font(.subheadline).foregroundStyle(.secondary)
                        FloorPlanView(package:map,showLandmarkLabels:false).frame(height:190)
                        NavigationLink {
                            SimulationEntry(package:map,api:api)
                        } label: {
                            Label("Start 3D walkthrough",systemImage:"figure.walk")
                                .frame(maxWidth:.infinity,minHeight:32)
                        }
                        .buttonStyle(.borderedProminent).tint(.touchSpaceMintFill).controlSize(.large)
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
                Text("These demos use virtual positions and saved map geometry. Questions require an online map assistant.")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding()
        }.touchSpaceBackground()
        .navigationTitle("Demo spaces")
        .navigationBarTitleDisplayMode(.inline)
    }
}
