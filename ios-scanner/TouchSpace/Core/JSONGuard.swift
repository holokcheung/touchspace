import Foundation

/// JSONDecoder accepts duplicate keys. Reject them before decoding portable files.
enum JSONGuard {
    static func validate(_ data:Data) throws {
        _ = try JSONSerialization.jsonObject(with:data,options:[.fragmentsAllowed])
        let bytes = Array(data)
        var stack: [Set<String>?] = [], index = 0
        func whitespace(_ byte:UInt8) -> Bool { byte == 32 || byte == 9 || byte == 10 || byte == 13 }
        while index < bytes.count {
            switch bytes[index] {
            case 123: stack.append(Set<String>()) // {
            case 91: stack.append(nil) // [
            case 125,93: _ = stack.popLast()
            case 34:
                let start = index
                index += 1
                while index < bytes.count {
                    if bytes[index] == 92 { index += 2; continue }
                    if bytes[index] == 34 { break }
                    index += 1
                }
                guard index < bytes.count else { throw TouchSpaceError.invalid("Invalid JSON string.") }
                var next = index+1
                while next < bytes.count && whitespace(bytes[next]) { next += 1 }
                if next < bytes.count && bytes[next] == 58 {
                    let key = try JSONDecoder().decode(String.self,from:Data(bytes[start...index]))
                    guard !stack.isEmpty, var keys = stack[stack.count-1] else { throw TouchSpaceError.invalid("Invalid JSON object.") }
                    guard keys.insert(key).inserted else { throw TouchSpaceError.invalid("Duplicate JSON key.") }
                    stack[stack.count-1] = keys
                }
            default: break
            }
            guard stack.count <= 64 else { throw TouchSpaceError.invalid("JSON exceeds supported nesting depth.") }
            index += 1
        }
    }
}
