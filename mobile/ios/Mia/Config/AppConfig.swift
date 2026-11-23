import Foundation

/// URL du backend et clés API. La clé MIA_API_KEY est exigée pour les clients
/// distants (iPhone via Tailscale) ; BRIEFING_API_KEY protège /api/briefing/.
enum AppConfig {
    private static let defaults = UserDefaults.standard

    static var baseURLString: String {
        get { defaults.string(forKey: "baseURL") ?? "http://127.0.0.1:8000" }
        set { defaults.set(newValue, forKey: "baseURL") }
    }

    static var miaApiKey: String? {
        get { Keychain.read("miaApiKey") }
        set {
            if let newValue { Keychain.save(newValue, for: "miaApiKey") } else { Keychain.delete("miaApiKey") }
        }
    }

    static var briefingKey: String? {
        get { Keychain.read("briefingKey") }
        set {
            if let newValue { Keychain.save(newValue, for: "briefingKey") } else { Keychain.delete("briefingKey") }
        }
    }

    static var baseURL: URL {
        URL(string: baseURLString) ?? URL(string: "http://127.0.0.1:8000")!
    }
}
