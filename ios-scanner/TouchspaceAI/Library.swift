import SwiftUI
import TouchspaceCore
import UniformTypeIdentifiers
import CryptoKit
import Security

extension UTType { static var touchspaceMap: UTType { UTType(exportedAs:"ai.touchspace.map",conformingTo:.zip) } }
struct LocalMap: Identifiable {
    var package: MapPackage
    var url: URL
    var id: String { package.manifest.mapId }
}
@MainActor final class MapLibrary: ObservableObject {
    @Published var maps=[LocalMap]()
    @Published var error: String?
    let directory: URL
    init(directory: URL? = nil) {
        self.directory=directory ?? FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("Maps",isDirectory:true)
        reload()
    }
    func reload() {
        do {
            try FileManager.default.createDirectory(at:directory,withIntermediateDirectories:true)
            let urls=try FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil).filter{$0.pathExtension=="touchspacemap"}
            var loaded=[LocalMap](), failures=[String]()
            for url in urls {
                do { let p=try MapPackage(data:boundedRead(url)); try WorldMapValidator.validate(p); loaded.append(LocalMap(package:p,url:url)) }
                catch { failures.append(url.lastPathComponent) }
            }
            maps=loaded.sorted{$0.package.manifest.title.localizedStandardCompare($1.package.manifest.title) == .orderedAscending}
            if !failures.isEmpty { error="Some saved maps could not be opened: \(failures.joined(separator:", "))." }
        } catch { self.error=error.localizedDescription }
    }
    func boundedRead(_ url: URL) throws -> Data {
        let size=try url.resourceValues(forKeys:[.fileSizeKey]).fileSize ?? 0
        guard size>0,size<=MapArchive.maxBytes else { throw MapError("Map package must be at most 64 MiB.") }
        return try Data(contentsOf:url)
    }
    @discardableResult func save(_ package: MapPackage) throws -> LocalMap {
        let data=try package.encoded(); try WorldMapValidator.validate(package)
        let url=directory.appendingPathComponent(package.manifest.mapId).appendingPathExtension("touchspacemap")
        try data.write(to:url,options:[.atomic,.completeFileProtectionUntilFirstUserAuthentication])
        var localURL=url; var values=URLResourceValues(); values.isExcludedFromBackup=true; try localURL.setResourceValues(values)
        reload(); return LocalMap(package:package,url:url)
    }
    func importMap(_ url: URL) {
        let access=url.startAccessingSecurityScopedResource(); defer { if access { url.stopAccessingSecurityScopedResource() } }
        do { let package=try MapPackage(data:boundedRead(url)); try WorldMapValidator.validate(package); try save(package) }
        catch { self.error=error.localizedDescription }
    }
    func addDemo() {
        guard let url=Bundle.main.url(forResource:"touchspace-demo",withExtension:"touchspacemap") else { error="The bundled demo is missing."; return }
        importMap(url)
    }
}

struct CatalogMap: Codable, Identifiable {
    var manifest: Manifest
    var visibility: String
    var checksum: String
    var byteSize: Int
    var warnings: [String]
    var worldDataStatus: String
    var id: String { manifest.mapId }
}
struct RemoteChat: Codable {
    struct Action: Codable { var type: String; var destinationId: String }
    var reply: String
    var sourceIds: [String]
    var action: Action?
    var interpreter: String
    var poseUsed: Bool
}
struct APIClient {
    var baseURL: URL
    var token: String
    init(address: String, token: String = "") throws {
        guard let url=URL(string:address), let host=url.host, url.user==nil, url.password==nil, url.query==nil, url.fragment==nil,
              url.scheme=="https" || (url.scheme=="http" && ["localhost","127.0.0.1","::1"].contains(host)) else { throw MapError("Use an HTTPS server URL, or http://localhost:8000 for the simulator.") }
        baseURL=url; self.token=token
    }
    private func request(_ path: String) -> URLRequest {
        var r=URLRequest(url:baseURL.appendingPathComponent("api/touchspace/"+path)); r.timeoutInterval=30
        if !token.isEmpty { r.setValue("Bearer "+token,forHTTPHeaderField:"Authorization") }; return r
    }
    private func checked(_ request: URLRequest, limit: Int = MapArchive.maxBytes) async throws -> Data {
        // Stream the response so an untrusted catalog cannot force an unbounded download.
        let (bytes,response)=try await URLSession.shared.bytes(for:request)
        guard let http=response as? HTTPURLResponse else { throw MapError("Invalid server response.") }
        guard response.expectedContentLength<=Int64(limit) else { throw MapError("Server response is too large.") }
        var data=Data(); for try await b in bytes { data.append(b); if data.count>limit { throw MapError("Server response exceeds the supported size.") } }
        guard (200..<300).contains(http.statusCode) else {
            struct E: Decodable { struct Detail:Decodable { var message:String }; var error:Detail }
            let explanation=(try? JSONDecoder().decode(E.self,from:data).error.message) ?? "Server returned HTTP \(http.statusCode)."
            throw MapError(explanation)
        }
        return data
    }
    func search(_ query: String) async throws -> [CatalogMap] {
        let r=request("maps"); var c=URLComponents(url:r.url!,resolvingAgainstBaseURL:false)!
        c.queryItems=[URLQueryItem(name:"q",value:query)]; var search=r; search.url=c.url
        return try JSONDecoder().decode([CatalogMap].self,from:await checked(search,limit:2*1024*1024))
    }
    func download(_ map: CatalogMap) async throws -> MapPackage {
        let data=try await checked(request("maps/\(map.id)/download"))
        let digest=SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()
        guard digest==map.checksum else { throw MapError("Downloaded package checksum does not match its catalog record.") }
        let p=try MapPackage(data:data)
        guard p.manifest.matchesCatalog(map.manifest) else { throw MapError("Downloaded metadata does not match its catalog record.") }
        try WorldMapValidator.validate(p); return p
    }
    func upload(_ package: MapPackage, publicly: Bool, consent: Bool) async throws -> CatalogMap {
        guard !publicly || consent else { throw MapError("Explicit publication consent is required.") }
        var r=request("maps"); r.httpMethod="POST"
        let boundary="touchspace-"+UUID().uuidString
        r.setValue("multipart/form-data; boundary=\(boundary)",forHTTPHeaderField:"Content-Type")
        var body=Data()
        func field(_ name:String,_ value:String) { body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8)) }
        field("visibility",publicly ? "public":"private"); field("publication_consent",consent ? "true":"false")
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(package.manifest.mapId).touchspacemap\"\r\nContent-Type: application/zip\r\n\r\n".utf8))
        body.append(try package.encoded()); body.append(Data("\r\n--\(boundary)--\r\n".utf8)); r.httpBody=body
        return try JSONDecoder().decode(CatalogMap.self,from:await checked(r,limit:2*1024*1024))
    }
    func chat(mapId:String,sessionId:UUID,message:String,pose:Pose?) async throws -> RemoteChat {
        struct Body: Encodable { var mapId:String; var sessionId:UUID; var message:String; var pose:Pose? }
        var r=request("chat"); r.httpMethod="POST"; r.setValue("application/json",forHTTPHeaderField:"Content-Type")
        let encoder=JSONEncoder(); encoder.dateEncodingStrategy = .iso8601
        r.httpBody=try encoder.encode(Body(mapId:mapId,sessionId:sessionId,message:message,pose:pose))
        return try JSONDecoder().decode(RemoteChat.self,from:await checked(r,limit:256*1024))
    }
}

/// Upload guard is a server credential, stored in the Keychain; provider API secrets never enter the app.
enum TokenStore {
    static let service="ai.touchspace.upload"
    static func read() -> String {
        let query: [String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service,kSecReturnData as String:true,kSecMatchLimit as String:kSecMatchLimitOne]
        var value: CFTypeRef?; guard SecItemCopyMatching(query as CFDictionary,&value)==errSecSuccess,let data=value as? Data else { return "" }; return String(data:data,encoding:.utf8) ?? ""
    }
    static func write(_ token:String) throws {
        let query: [String:Any]=[kSecClass as String:kSecClassGenericPassword,kSecAttrService as String:service]
        SecItemDelete(query as CFDictionary)
        if token.isEmpty { return }
        var add=query; add[kSecValueData as String]=Data(token.utf8); add[kSecAttrAccessible as String]=kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(add as CFDictionary,nil)==errSecSuccess else { throw MapError("Could not save the upload credential in Keychain.") }
    }
}
