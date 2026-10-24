import SwiftUI
import TouchspaceCore

struct ChatLine: Identifiable { let id=UUID(); var question:String; var reply:String; var sources:[String]; var requiresLivePose:Bool }
struct ExploreView: View {
    var map:LocalMap
    var startLive:Bool
    @Environment(\.scenePhase) var scenePhase
    @AppStorage("serverAddress") var address="http://localhost:8000"
    @StateObject private var positioning=Positioning()
    @StateObject private var audio=AudioGuide()
    @StateObject private var speech=SpeechInput()
    @State private var guidance=Guidance()
    @State private var assistant=LocalAssistant()
    @State private var question=""
    @FocusState private var questionFocused:Bool
    @State private var destination=""
    @State private var chats=[ChatLine]()
    @State private var busy=false
    @State private var screenActive=true
    @State private var serverChat=false
    @State private var sessionId=UUID()
    @State private var error:String?
    @State private var lastInstructionKey=""
    @State private var lastInstructionTime=Date.distantPast
    var engine:SpatialEngine { SpatialEngine(package:map.package) }
    var body:some View {
      ScrollViewReader { scroll in
        List {
            Section("Position") {
                Label(positioning.status == .localized ? "Localized" : positioning.status == .relocalizing ? "Relocalizing" : positioning.status == .limited ? "Limited tracking":"Map-only / positioning unavailable",systemImage:positioning.status == .localized ? "location.fill":"location.slash")
                    .font(.headline).accessibilityIdentifier("trackingStatus")
                Text(positioning.explanation)
                LabeledContent("Current room",value:positioning.pose.flatMap{engine.room(at:$0.position)?.name} ?? "Unknown")
                if map.package.manifest.worldMapIncluded {
                    Button("Retry automatic positioning") { Task { await positioning.start(map.package) } }.frame(minHeight:44)
                    CameraPreview(session:positioning.session).frame(height:150).clipShape(RoundedRectangle(cornerRadius:12)).accessibilityHidden(true)
                }
            }
            Section("Navigation") {
                Picker("Destination",selection:$destination) {
                    Text("Choose a landmark").tag("")
                    ForEach(map.package.landmarks.landmarks) { lm in Text(lm.name).tag(lm.id) }
                }.accessibilityIdentifier("destinationPicker")
                Button(guidance.state == .idle || guidance.state == .arrived ? "Start navigation":"Resume / recalculate route") { beginNavigation() }.frame(minHeight:44).disabled(destination.isEmpty || positioning.pose==nil)
                Text(guidance.instruction).font(.headline).accessibilityIdentifier("routeInstruction")
                Notice(text:"Directions are relative to your phone, which may face differently from your body. Stop if unsure. The map does not detect current obstacles.")
            }
            Section("Conversation") {
                if chats.isEmpty { Text("Try “how are the rooms connected?” or “what is to my right?”").foregroundStyle(.secondary) }
                ForEach(chats) { line in
                    VStack(alignment:.leading,spacing:8) {
                        Text("You: \(line.question)").font(.headline)
                        Text(line.reply).textSelection(.enabled)
                        if !sourceDescription(line.sources).isEmpty { Text("Map sources: "+sourceDescription(line.sources)).font(.caption).foregroundStyle(.secondary) }
                    }.padding(.vertical,6).accessibilityElement(children:.combine).id(line.id)
                }
                if busy { ProgressView("Reading map facts…") }
                if let error { Text(error).foregroundStyle(.red) }
                if let error=speech.error { Text(error).foregroundStyle(.red) }
            }
            Section("Audio and privacy") {
                Toggle("Mute speech and cues",isOn:$audio.muted)
                Toggle("Speech only",isOn:$audio.speechOnly)
                if !audio.speechOnly { Slider(value:$audio.cueInterval,in:3...15,step:1) { Text("Cue interval") }; Text("Waypoint beacon every \(Int(audio.cueInterval)) seconds. Stereo headphones distinguish left and right.").font(.footnote) }
                Toggle("Use server assistant for this map",isOn:$serverChat)
                if serverChat { Notice(text:"Each submitted question and current phone pose will be sent to your configured server. The map must already be stored there. No camera frames or continuous pose updates are sent.") }
            }
            Section("Supplemental visual plan") { PlanView(package:map.package,pose:positioning.pose,route:guidance.route).frame(height:230).accessibilityHidden(true) }
        }
        .navigationTitle("Explore")
        .safeAreaInset(edge:.bottom) {
            VStack(spacing:8) {
                HStack(alignment:.bottom) {
                    TextField("Type a question",text:$question,axis:.vertical).focused($questionFocused).lineLimit(1...3).textFieldStyle(.roundedBorder).accessibilityIdentifier("questionInput").submitLabel(.send).onSubmit { Task { await ask() } }
                    Button { Task { await ask() } } label:{ Image(systemName:"arrow.up.circle.fill").font(.title).frame(minWidth:44,minHeight:44) }.accessibilityLabel("Send question").accessibilityIdentifier("sendQuestion").disabled(question.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || busy)
                }
                Button {
                    audio.silence()
                    if speech.recording { speech.stop(); question=speech.transcript }
                    else { Task { await speech.start() } }
                } label:{ Label(speech.recording ? "Finish dictation":"Ask Touchspace AI",systemImage:speech.recording ? "stop.circle.fill":"mic.fill").font(.headline).frame(maxWidth:.infinity,minHeight:48) }.buttonStyle(.borderedProminent).tint(.touchspaceButton).foregroundStyle(.white).accessibilityIdentifier("askMicrophone").accessibilityHint("Dictate a question on device, then use Send question. Typed input is also available.")
                HStack {
                    Button("Repeat") { repeatCurrent() }.frame(maxWidth:.infinity,minHeight:44)
                    Button("Pause") { guidance.pause(); audio.silence(); audio.say(guidance.instruction,repeatAllowed:true) }.frame(maxWidth:.infinity,minHeight:44).disabled(guidance.state != .navigating)
                    Button("End") { guidance.end(); audio.silence() }.frame(maxWidth:.infinity,minHeight:44).disabled(guidance.state == .idle)
                }.buttonStyle(.bordered)
            }.padding().background(.regularMaterial)
        }
        .task { if startLive { await positioning.start(map.package) } }
        .onChange(of:speech.transcript) { _,new in question=new }
        .onChange(of:positioning.status) { _,status in
            if status != .localized { audio.silence(); guidance.update(pose:nil,engine:engine) }
            if !speech.recording { audio.say(positioning.explanation,repeatAllowed:true) }
        }
        .onReceive(positioning.$pose) { pose in updateGuidance(pose) }
        .onChange(of:scenePhase) { _,phase in
            screenActive=phase == .active
            if phase != .active { positioning.stop(); speech.stop(); guidance.update(pose:nil,engine:engine); audio.silence() }
        }
        .onAppear {screenActive=true}
        .onDisappear { screenActive=false; positioning.stop(); speech.stop(); audio.silence() }
        .scrollDismissesKeyboard(.interactively)
        .onChange(of:chats.count) { _,_ in if let id=chats.last?.id { withAnimation { scroll.scrollTo(id,anchor:.center) } } }
      }
    }
    func sourceDescription(_ ids:[String])->String {
        var names=[String]()
        for id in ids {
            let name:String?
            if let landmark=map.package.landmarks.landmarks.first(where:{$0.id==id}) { name="\(landmark.name) (\(landmark.provenance == "scan" ? "scan-derived":"volunteer label"))" }
            else if let room=map.package.geometry.rooms.first(where:{$0.id==id}) {name=room.name}
            else {name=map.package.navigation.doors.first(where:{$0.id==id})?.name}
            if let name,!names.contains(name) {names.append(name)}
        }
        return names.joined(separator:", ")
    }
    func repeatCurrent() {
        let text:String
        if guidance.state != .idle {text=guidance.instruction}
        else if let line=chats.last, !line.requiresLivePose {text=line.reply}
        else {text=positioning.explanation}
        // Pose-dependent answers describe a past observation; obtain a fresh answer instead of replaying it.
        audio.say(text,repeatAllowed:true)
    }
    func updateGuidance(_ pose:Pose?) {
        let old=guidance.state
        guidance.update(pose:pose,engine:engine)
        if old != guidance.state { audio.silence(); if !speech.recording { audio.say(guidance.instruction,repeatAllowed:true) } }
        guard !speech.recording, guidance.state == .navigating, let cue=guidance.cue else { return }
        let key="\(guidance.nextIndex):\(cue.direction)"
        if key != lastInstructionKey && Date().timeIntervalSince(lastInstructionTime)>4 {
            audio.say(guidance.instruction,repeatAllowed:true); lastInstructionKey=key; lastInstructionTime=Date()
        }
        audio.beep(pan:cue.stereoPan)
    }
    func beginNavigation() {
        guard let pose=positioning.pose, let lm=map.package.landmarks.landmarks.first(where:{$0.id==destination}) else { return }
        do { guidance.start(try engine.route(from:pose,to:lm)); lastInstructionKey=""; lastInstructionTime = .distantPast; updateGuidance(pose) }
        catch { self.error=error.localizedDescription; audio.say(error.localizedDescription,repeatAllowed:true) }
    }
    func ask() async {
        let text=question.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !text.isEmpty,!busy else { return }
        guard text.count<=2000 else { error="Please keep questions under 2,000 characters."; return }
        questionFocused=false; speech.stop(); audio.silence(); busy=true; question=""; error=nil; defer{busy=false}
        let submittedPose=positioning.pose
        var requiresLivePose=submittedPose != nil
        var answer:AssistantAnswer
        if serverChat {
            do {
                let reply=try await APIClient(address:address,token:TokenStore.read()).chat(mapId:map.id,sessionId:sessionId,message:text,pose:submittedPose)
                requiresLivePose=reply.poseUsed
                let ids=Set(map.package.landmarks.landmarks.map(\.id))
                let target=reply.action.flatMap { $0.type=="destination" && ids.contains($0.destinationId) ? $0.destinationId:nil }
                if reply.poseUsed, positioning.pose?.stillMatches(submittedPose,for:map.package.manifest) != true {
                    answer=AssistantAnswer(reply:"Your phone moved or tracking became uncertain while I was checking. Ask again for current spatial directions.")
                } else { answer=AssistantAnswer(reply:reply.reply,sourceIds:reply.sourceIds,destinationId:target) }
            } catch {
                answer=assistant.answer(text,package:map.package,pose:positioning.pose)
                self.error="Server assistant unavailable: \(error.localizedDescription) Using local map facts."
            }
        } else { answer=assistant.answer(text,package:map.package,pose:positioning.pose) }
        guard screenActive else{return}
        // A server suggestion selects a landmark; starting navigation always invokes the local engine.
        if let id=answer.destinationId { destination=id }
        chats.append(ChatLine(question:text,reply:answer.reply,sources:answer.sourceIds,requiresLivePose:requiresLivePose)); audio.say(answer.reply,repeatAllowed:true)
    }
}

struct PlanView: View {
    var package:MapPackage; var pose:Pose?; var route:Route?
    var body:some View {
        Canvas { context,size in
            let points=package.geometry.rooms.flatMap(\.polygon)
            guard let minX=points.map(\.x).min(),let maxX=points.map(\.x).max(),let minZ=points.map(\.z).min(),let maxZ=points.map(\.z).max() else { return }
            let scale=min((size.width-24)/max(1,maxX-minX),(size.height-24)/max(1,maxZ-minZ))
            func screen(_ p:Point)->CGPoint { CGPoint(x:12+(p.x-minX)*scale,y:12+(p.z-minZ)*scale) }
            func polygon(_ points:[Point])->Path { Path { path in guard let first=points.first else{return}; path.move(to:screen(first)); for p in points.dropFirst(){path.addLine(to:screen(p))}; path.closeSubpath() } }
            for r in package.geometry.rooms { context.fill(polygon(r.polygon),with:.color(.teal.opacity(0.12))); context.stroke(polygon(r.polygon),with:.color(.secondary),lineWidth:1) }
            for o in package.geometry.obstacles { context.fill(polygon(o.polygon),with:.color(.secondary.opacity(0.5))) }
            for wall in package.geometry.walls { let path=Path{p in p.move(to:screen(wall.a));p.addLine(to:screen(wall.b))};context.stroke(path,with:.color(.primary),lineWidth:3) }
            if let route { let path=Path{p in for (i,v) in route.waypoints.enumerated(){ if i==0 {p.move(to:screen(v))} else {p.addLine(to:screen(v))} }};context.stroke(path,with:.color(.teal),style:StrokeStyle(lineWidth:3,dash:[5,4])) }
            for lm in package.landmarks.landmarks { let p=screen(lm.position); context.fill(Path(ellipseIn:CGRect(x:p.x-4,y:p.y-4,width:8,height:8)),with:.color(.orange)) }
            if let pose {
                let p=screen(pose.position);context.fill(Path(ellipseIn:CGRect(x:p.x-6,y:p.y-6,width:12,height:12)),with:.color(.blue))
                let end=CGPoint(x:p.x+sin(pose.heading)*18,y:p.y-cos(pose.heading)*18)
                context.stroke(Path{p in p.move(to:screen(pose.position));p.addLine(to:end)},with:.color(.blue),lineWidth:3)
            }
        }
    }
}
