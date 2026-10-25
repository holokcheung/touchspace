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

extension UIColor {
    /// Screen background: light mint #E6F7F2 (tint is 4.8:1 on it), deep mint #0B2E27 in dark mode.
    static let touchSpaceBackground = UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red:0x0B/255.0,green:0x2E/255.0,blue:0x27/255.0,alpha:1)
            : UIColor(red:0xE6/255.0,green:0xF7/255.0,blue:0xF2/255.0,alpha:1)
    }
}

extension Color {
    static let touchSpaceMint = Color(uiColor:.touchSpaceMint)
    static let touchSpaceBackground = Color(uiColor:.touchSpaceBackground)
}

extension View {
    /// Mint behind a List, Form or ScrollView instead of the system white or grey.
    func touchSpaceBackground() -> some View {
        scrollContentBackground(.hidden).background(Color.touchSpaceBackground.ignoresSafeArea())
    }
}

@main struct TouchSpaceApp: App {
    @StateObject private var library = MapLibrary()
    @State private var importError: String?
    init() {
        // Alerts, sheets and UIKit-backed controls take the window's tint, not SwiftUI's.
        UIWindow.appearance().tintColor = .touchSpaceMint
        // Mint navigation bars, scrolled or not.
        let bar = UINavigationBarAppearance()
        bar.configureWithOpaqueBackground()
        bar.backgroundColor = .touchSpaceBackground
        bar.shadowColor = .clear
        UINavigationBar.appearance().standardAppearance = bar
        UINavigationBar.appearance().scrollEdgeAppearance = bar
        UINavigationBar.appearance().compactAppearance = bar
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
