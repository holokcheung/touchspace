import SwiftUI

struct AskSheet: View {
    let package: MapPackage
    let api: APIClient?
    var pose: (() -> VerifiedPose?)? = nil
    var simulatedPose: (() -> SimulatedPose?)? = nil
    var audio: AudioGuidance? = nil
    var onNavigate: ((String) -> Void)? = nil
    let sessionId: UUID
    @StateObject private var input = SpeechInput()
    @State private var message = ""
    @State private var answer = "Ask about rooms, destinations or confirmed connections. Direction questions require fresh AR localization."
    @State private var busy = false
    @Environment(\.dismiss) private var dismiss
    @AccessibilityFocusState private var answerFocused: Bool
    @FocusState private var questionFocused: Bool
    var body: some View {
        NavigationStack {
            Form {
                Section("Ask about this map") {
                    TextField("Your question",text:$message,axis:.vertical).lineLimit(2...4).accessibilityLabel("Type a map question").focused($questionFocused)
                    Button(input.recording ? "Stop microphone" : "Use microphone",systemImage:input.recording ? "stop.circle" : "mic") {
                        if input.recording { input.stop(); message = input.transcript }
                        else { audio?.stop(); Task { await input.start() } }
                    }
                    if let error = input.error { Text(error).foregroundStyle(.red) }
                    Button("Ask",systemImage:"paperplane") { Task { await ask() } }.disabled(message.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || busy)
                }
                Section("Answer") { Text(answer).accessibilityFocused($answerFocused) }
                if busy { ProgressView("Consulting the saved map") }
                if let audio { Button("Interrupt speech",systemImage:"speaker.slash") { audio.stop() } }
                Text("Questions go to your configured backend when online. Microphone transcription stays on device. No camera images are sent.").font(.footnote)
            }
            .navigationTitle("Ask TouchSpace")
            .toolbar { ToolbarItem(placement:.confirmationAction) { Button("Done") { audio?.stop(); dismiss() } } }
            .onChange(of:input.transcript) { _,new in message = new }
            .onDisappear { input.stop() }
        }
        .presentationDetents([.medium,.large])
    }
    private func ask() async {
        busy = true; questionFocused = false; input.stop(); audio?.stop()
        defer { busy = false; answerFocused = true }
        if package.manifest.isSynthetic || api == nil {
            await askLocally()
            return
        }
        guard let api else { return }
        do {
            let reply = try await api.ask(map:package.id,session:sessionId,message:message,pose:pose?())
            answer = reply.answer; audio?.say(answer,urgent:true)
            if let action = reply.actions.first, action.type == "navigate", package.landmarks.landmarks.contains(where: { $0.id == action.destinationId }) {
                dismiss(); onNavigate?(action.destinationId)
            }
        } catch { await askLocally() }
    }
    private func askLocally() async {
        let package = package, message = message, simulated = simulatedPose?()
        do {
            let reply = try await Task.detached { try OfflineMapAssistant.answer(message,package:package,simulatedPose:simulated) }.value
            answer = reply.answer; audio?.say(answer,urgent:true)
            if let id = reply.destinationId, let onNavigate { dismiss(); onNavigate(id) }
        } catch { answer = error.localizedDescription; audio?.say(answer,urgent:true) }
    }
}
