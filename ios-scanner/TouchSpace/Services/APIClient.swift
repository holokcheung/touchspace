import Foundation
import Security

struct APIClient {
    var baseURL: URL
    var token: String? { CredentialStore.get("token.\(baseURL.absoluteString)") }
    func endpoint(_ path: String) -> URL { baseURL.appendingPathComponent("api/touchspace/"+path) }
    func request(_ path: String, method: String = "GET", data: Data? = nil, contentType: String = "application/json") async throws -> Data {
        var request = URLRequest(url:endpoint(path)); request.httpMethod = method
        request.timeoutInterval = path == "chat" ? 40 : 60
        request.httpBody = data
        request.setValue(contentType,forHTTPHeaderField:"Content-Type")
        if let token { request.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization") }
        return try await send(request)
    }
    func send(_ request: URLRequest) async throws -> Data {
        let (data,response) = try await URLSession.shared.data(for:request)
        guard let response = response as? HTTPURLResponse else { throw TouchSpaceError.invalid("No response from server.") }
        guard (200..<300).contains(response.statusCode) else {
            // Never include request headers, prompts or raw provider errors in UI/logs.
            let object = try? JSONSerialization.jsonObject(with:data) as? [String:Any]
            let message = object?["detail"] as? String ?? (object?["error"] as? [String:Any])?["message"] as? String
            throw TouchSpaceError.invalid(message ?? "Server request failed (\(response.statusCode)).")
        }
        return data
    }
    func search(_ query: String) async throws -> [MapSummary] {
        var components = URLComponents(url:endpoint("maps"),resolvingAgainstBaseURL:false)!
        components.queryItems = [URLQueryItem(name:"q",value:query)]
        let data = try await send(URLRequest(url:components.url!))
        return try JSONDecoder().decode([MapSummary].self,from:data)
    }
    func download(_ id: UUID) async throws -> URL {
        var request = URLRequest(url:endpoint("maps/\(id.uuidString)/download"))
        if let token { request.setValue("Bearer \(token)",forHTTPHeaderField:"Authorization") }
        let (temp,response) = try await URLSession.shared.download(for:request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else { throw TouchSpaceError.invalid("Map download failed.") }
        guard (try temp.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? PackageCodec.maximum+1) <= PackageCodec.maximum else { throw TouchSpaceError.invalid("Download exceeds 64 MB.") }
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString+".touchspacemap")
        try FileManager.default.moveItem(at:temp,to:destination)
        return destination
    }
    func pair(code: String) async throws {
        struct Pair: Encodable { var code: String; var installationId: String }
        struct Session: Decodable { var token: String; var expiresAt: Int }
        var installation = CredentialStore.get("installationId")
        if installation == nil { installation = UUID().uuidString; try CredentialStore.set(installation!,key:"installationId") }
        let body = try JSONEncoder().encode(Pair(code:code,installationId:installation!))
        // Pairing must also work after a prior credential expires.
        var request = URLRequest(url:endpoint("publishing/session")); request.httpMethod = "POST"; request.httpBody = body
        request.setValue("application/json",forHTTPHeaderField:"Content-Type")
        let result = try JSONDecoder().decode(Session.self,from:await send(request))
        try CredentialStore.set(result.token,key:"token.\(baseURL.absoluteString)")
    }
    func upload(_ url: URL, makePublic: Bool, consent: Bool) async throws {
        guard !makePublic || consent else { throw TouchSpaceError.invalid("Explicit consent is required to publish a public map.") }
        let boundary = UUID().uuidString
        var body = Data()
        func append(_ text: String) { body.append(Data(text.utf8)) }
        for (name,value) in [("visibility",makePublic ? "public" : "private"),("publication_consent",consent ? "true" : "false")] {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"map.touchspacemap\"\r\nContent-Type: application/vnd.touchspace.map+zip\r\n\r\n")
        body.append(try Data(contentsOf:url)); append("\r\n--\(boundary)--\r\n")
        _ = try await request("maps",method:"POST",data:body,contentType:"multipart/form-data; boundary=\(boundary)")
    }
    func transcribeLocally(_ audio:Data) async throws -> String {
        let boundary = UUID().uuidString
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"local_only\"\r\n\r\ntrue\r\n".utf8)
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"question.wav\"\r\nContent-Type: audio/wav\r\n\r\n".utf8))
        body.append(audio); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var request = URLRequest(url:baseURL.appendingPathComponent("api/stt"))
        request.httpMethod = "POST"; request.httpBody = body; request.timeoutInterval = 45
        request.setValue("multipart/form-data; boundary=\(boundary)",forHTTPHeaderField:"Content-Type")
        struct Transcript: Decodable { let text:String }
        do {
            let text = try JSONDecoder().decode(Transcript.self,from:await send(request)).text.trimmingCharacters(in:.whitespacesAndNewlines)
            guard !text.isEmpty else { throw TouchSpaceError.invalid("No speech was detected. Check the microphone input and try again.") }
            return text
        } catch let error as URLError where error.code != .cancelled {
            throw TouchSpaceError.invalid("Cannot reach local transcription. Start the TouchSpace backend on your Mac and check the server URL in Settings.")
        }
    }
    func ask(map: UUID, session: UUID, message: String, pose: VerifiedPose?) async throws -> ChatReply {
        struct Question: Encodable { var mapId: UUID; var sessionId: UUID; var message: String; var pose: VerifiedPose? }
        let body = try JSONEncoder().encode(Question(mapId:map,sessionId:session,message:message,pose:pose))
        return try JSONDecoder().decode(ChatReply.self,from:await request("chat",method:"POST",data:body))
    }
}

enum CredentialStore {
    static func get(_ key: String) -> String? {
        let query: [String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:"ai.touchspace.credentials",kSecAttrAccount as String:key,kSecReturnData as String:true,kSecMatchLimit as String:kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary,&result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data:data,encoding:.utf8)
    }
    static func set(_ value: String, key: String) throws {
        let query: [String:Any] = [kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:"ai.touchspace.credentials",kSecAttrAccount as String:key]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = Data(value.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(item as CFDictionary,nil) == errSecSuccess else { throw TouchSpaceError.invalid("Could not save publishing credential in Keychain.") }
    }
}
