import SwiftUI
import UIKit

extension UIColor {
    /// TouchSpace mint instead of the system blue, so the app isn't mistaken for a built-in one.
    /// Light #00796B is 5.3:1 on white; dark #63E6BE is 11:1 on the dark list background.
    static let touchSpaceMint = UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red:0x63/255.0,green:0xE6/255.0,blue:0xBE/255.0,alpha:1)
            : UIColor(red:0x00/255.0,green:0x79/255.0,blue:0x6B/255.0,alpha:1)
    }
}

extension Color { static let touchSpaceMint = Color(uiColor:.touchSpaceMint) }

@main struct TouchSpaceApp: App {
    @StateObject private var library = MapLibrary()
    @State private var importError: String?
    init() {
        // Alerts, sheets and UIKit-backed controls take the window's tint, not SwiftUI's.
        UIWindow.appearance().tintColor = .touchSpaceMint
    }
    var body: some Scene {
        WindowGroup {
            HomeView().environmentObject(library)
                .tint(.touchSpaceMint)
                .onOpenURL { url in
                    do { _ = try library.importMap(url) }
                    catch { importError = error.localizedDescription }
                }
                .alert("Import failed",isPresented:Binding(get:{ importError != nil },set:{ if !$0 { importError=nil } })) { Button("OK") { importError=nil } } message: { Text(importError ?? "") }
        }
    }
}
