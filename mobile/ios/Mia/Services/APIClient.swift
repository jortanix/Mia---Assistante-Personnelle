import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case unauthorized
    case server(status: Int, message: String?)
    case decoding
    case transport(any Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "URL du backend invalide (voir Réglages)."
        case .unauthorized:
            return "Accès refusé : clé API manquante ou invalide."
        case .server(let status, let message):
            return message ?? "Erreur serveur (\(status))."
        case .transport(let error):
            return "Connexion impossible : \(error.localizedDescription)"
        case .decoding:
            return "La réponse du serveur est illisible."
        }
    }
}

/// Client HTTP minimal vers l'API Mia. Envoie les clés du trousseau quand
/// elles sont définies. Le chat streamé est géré par ChatService.
struct APIClient {
    private let baseURL: URL
    private let apiKey: String?
    private let briefingKey: String?

    init() {
        self.baseURL = AppConfig.baseURL
        self.apiKey = AppConfig.miaApiKey
        self.briefingKey = AppConfig.briefingKey
    }

    private var session: URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 90
        return URLSession(configuration: config)
    }

    private func makeRequest(
        _ path: String,
        method: String = "GET",
        body: (any Encodable)? = nil,
        useBriefingKey: Bool = false
    ) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw APIError.invalidURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let body {
            request.httpBody = try JSONEncoder.mia().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if useBriefingKey {
            if let briefingKey {
                request.setValue("Bearer \(briefingKey)", forHTTPHeaderField: "Authorization")
            }
        } else if let apiKey {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    /// Requête JSON typée.
    func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        body: (any Encodable)? = nil,
        useBriefingKey: Bool = false
    ) async throws -> T {
        let request = try makeRequest(path, method: method, body: body, useBriefingKey: useBriefingKey)
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status != 401 else { throw APIError.unauthorized }
        guard (200...299).contains(status) else {
            let message = try? JSONDecoder().decode(ServerError.self, from: data).humanMessage
            throw APIError.server(status: status, message: message)
        }
        do {
            return try JSONDecoder.mia().decode(T.self, from: data)
        } catch {
            throw APIError.decoding
        }
    }

    /// Requête sans corps de réponse (DELETE…).
    func requestNoContent(
        _ path: String,
        method: String = "DELETE"
    ) async throws {
        let request = try makeRequest(path, method: method)
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status != 401 else { throw APIError.unauthorized }
        guard (200...299).contains(status) else {
            let message = try? JSONDecoder().decode(ServerError.self, from: data).humanMessage
            throw APIError.server(status: status, message: message)
        }
    }

    /// Corps de la session pour le stream NDJSON.
    func streamSession(_ path: String, body: some Encodable) async throws -> (URLSession.AsyncBytes, HTTPURLResponse) {
        let request = try makeRequest(path, method: "POST", body: body)
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.decoding }
        return (bytes, http)
    }
}

private struct ServerError: Decodable {
    let error: String?

    var humanMessage: String? { error }
}
