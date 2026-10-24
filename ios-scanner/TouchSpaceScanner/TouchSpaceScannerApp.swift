import SwiftUI

@main
struct TouchSpaceScannerApp: App {
    @StateObject private var store = ScanStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
