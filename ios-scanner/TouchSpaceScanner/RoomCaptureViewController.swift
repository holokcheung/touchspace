import RoomPlan
import SwiftUI
import UIKit

/// Hosts Apple's `RoomCaptureView`, which provides the scanning UI, coaching and the
/// post-scan preview. `RoomCaptureViewDelegate` inherits `NSCoding`, so the delegate is a
/// view controller (as in Apple's sample code) rather than a plain coordinator object.
final class RoomCaptureViewController: UIViewController, RoomCaptureViewDelegate, RoomCaptureSessionDelegate {
    var onProcessed: ((CapturedRoom) -> Void)?
    var onFailed: ((Error) -> Void)?
    var onInstruction: ((RoomCaptureSession.Instruction) -> Void)?

    private var captureView: RoomCaptureView!
    private var isScanning = false

    override func viewDidLoad() {
        super.viewDidLoad()
        captureView = RoomCaptureView(frame: view.bounds)
        captureView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        captureView.delegate = self
        captureView.captureSession.delegate = self
        view.addSubview(captureView)
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        startScanning()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if isScanning { captureView.captureSession.stop() }
    }

    func startScanning() {
        guard !isScanning else { return }
        isScanning = true
        captureView.captureSession.run(configuration: RoomCaptureSession.Configuration())
    }

    /// Ends capture. RoomPlan then post-processes the scan and calls `captureView(didPresent:error:)`.
    func stopScanning() {
        guard isScanning else { return }
        isScanning = false
        captureView.captureSession.stop()
    }

    // MARK: RoomCaptureViewDelegate

    func captureView(shouldPresent roomDataForProcessing: CapturedRoomData, error: Error?) -> Bool {
        if let error {
            onFailed?(error)
            return false
        }
        return true
    }

    func captureView(didPresent processedResult: CapturedRoom, error: Error?) {
        if let error {
            onFailed?(error)
        } else {
            onProcessed?(processedResult)
        }
    }

    // MARK: RoomCaptureSessionDelegate

    func captureSession(_ session: RoomCaptureSession, didProvide instruction: RoomCaptureSession.Instruction) {
        onInstruction?(instruction)
    }
}

/// SwiftUI wrapper. `controller` is handed back so the surrounding view can call `stopScanning()`.
struct RoomCaptureRepresentable: UIViewControllerRepresentable {
    @Binding var controller: RoomCaptureViewController?
    var onProcessed: (CapturedRoom) -> Void
    var onFailed: (Error) -> Void
    var onInstruction: (RoomCaptureSession.Instruction) -> Void

    func makeUIViewController(context: Context) -> RoomCaptureViewController {
        let vc = RoomCaptureViewController()
        vc.onProcessed = onProcessed
        vc.onFailed = onFailed
        vc.onInstruction = onInstruction
        DispatchQueue.main.async { controller = vc }
        return vc
    }

    func updateUIViewController(_ vc: RoomCaptureViewController, context: Context) {}
}

extension RoomCaptureSession.Instruction {
    /// Spoken/visible text for coaching instructions, so VoiceOver users get them too.
    var message: String? {
        switch self {
        case .moveCloseToWall: return "Move closer to the wall."
        case .moveAwayFromWall: return "Move away from the wall."
        case .slowDown: return "Slow down."
        case .turnOnLight: return "Turn on more lights."
        case .lowTexture: return "Point at an area with more detail."
        case .normal: return nil
        @unknown default: return nil
        }
    }
}
