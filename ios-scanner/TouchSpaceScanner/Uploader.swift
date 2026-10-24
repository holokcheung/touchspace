import Foundation

/// Sends a saved scan to the TouchSpace backend (`POST /api/scans`, multipart field `file`).
enum Uploader {
    struct Result {
        let mapID: String
        let mapName: String
        let warnings: [String]
    }

    enum UploadError: LocalizedError {
        case badServerAddress
        case server(String)
        case unexpectedResponse

        var errorDescription: String? {
            switch self {
            case .badServerAddress: return "The server address is not valid. Use something like http://192.168.1.20:8000"
            case .server(let message): return message
            case .unexpectedResponse: return "The server sent a response TouchSpace could not read."
            }
        }
    }

    static func upload(fileURL: URL, displayName: String, server: String) async throws -> Result {
        let trimmed = server.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let base = URL(string: trimmed), base.scheme == "http" || base.scheme == "https", base.host != nil else {
            throw UploadError.badServerAddress
        }
        let endpoint = base.appendingPathComponent("api/scans")
        let boundary = "TouchSpace-\(UUID().uuidString)"
        var request = URLRequest(url: endpoint, timeoutInterval: 60)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }
        field("name", displayName)
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(fileURL.lastPathComponent)\"\r\nContent-Type: application/json\r\n\r\n".data(using: .utf8)!)
        body.append(try Data(contentsOf: fileURL))
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        let (data, response) = try await URLSession.shared.upload(for: request, from: body)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]

        guard (200..<300).contains(status) else {
            let error = json?["error"] as? [String: Any]
            var message = (error?["message"] as? String) ?? "Upload failed (HTTP \(status))."
            if let details = error?["details"] as? [String], !details.isEmpty {
                message += "\n" + details.prefix(3).joined(separator: "\n")
            }
            throw UploadError.server(message)
        }
        guard let map = json?["map"] as? [String: Any], let id = map["id"] as? String else {
            throw UploadError.unexpectedResponse
        }
        let issues = (json?["issues"] as? [[String: Any]]) ?? []
        return Result(
            mapID: id,
            mapName: (map["name"] as? String) ?? displayName,
            warnings: issues.filter { ($0["severity"] as? String) != "info" }.compactMap { $0["message"] as? String }
        )
    }
}
