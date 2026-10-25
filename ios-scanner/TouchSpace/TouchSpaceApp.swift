import SwiftUI

@main struct TouchSpaceApp: App {
    @StateObject private var library = MapLibrary()
    @State private var importError: String?
    var body: some Scene {
        WindowGroup {
            HomeView().environmentObject(library)
                .onOpenURL { url in
                    do { _ = try library.importMap(url) }
                    catch { importError = error.localizedDescription }
                }
                .alert("Import failed",isPresented:Binding(get:{ importError != nil },set:{ if !$0 { importError=nil } })) { Button("OK") { importError=nil } } message: { Text(importError ?? "") }
        }
    }
}
