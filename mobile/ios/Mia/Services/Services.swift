import Foundation

/// Services métier : chat (standard et streamé), briefing, tâches, mémoire,
/// rappels, sessions de concentration.
enum ChatService {
    static let client = APIClient()

    /// Chat standard : retourne la réponse texte de Mia.
    static func ask(_ message: String, conversationID: Int? = nil, useMemory: Bool = false) async throws -> String {
        let body = ChatRequest(message: message, conversationID: conversationID, useMemory: useMemory)
        let reply: ChatReply = try await client.request("/api/chat/", method: "POST", body: body)
        if let text = reply.reply, !text.isEmpty {
            return text
        }
        if let proposal = reply.actionProposal {
            return "Créer la tâche « \(proposal.data?.title ?? "?" ) » ? (voir onglet Tâches pour confirmer)"
        }
        return "Aucune réponse."
    }

    /// Chat streamé : concatène les deltas et émet les événements en direct.
    static func stream(
        _ message: String,
        conversationID: Int? = nil,
        useMemory: Bool = false,
        onEvent: @escaping (StreamEvent) -> Void
    ) async throws -> String {
        let body = ChatRequest(message: message, conversationID: conversationID, useMemory: useMemory)
        let (bytes, response) = try await client.streamSession("/api/chat/stream/", body: body)
        let status = response.statusCode
        guard status != 401 else { throw APIError.unauthorized }
        guard (200...299).contains(status) else { throw APIError.server(status: status, message: nil) }

        var buffer = Data()
        var fullText = ""
        for try await byte in bytes {
            buffer.append(byte)
            while let newline = buffer.firstIndex(of: 0x0A) {
                let line = buffer[..<newline]
                buffer = buffer[buffer.index(after: newline)...]
                guard !line.isEmpty,
                      let event = try? JSONDecoder.mia().decode(StreamEvent.self, from: line)
                else { continue }
                if let delta = event.content {
                    fullText += delta
                }
                onEvent(event)
                if event.type == "done" || event.type == "error" {
                    return fullText
                }
            }
        }
        return fullText
    }
}

enum BriefingService {
    static let client = APIClient()

    static func today() async throws -> Briefing {
        try await client.request("/api/briefing/", useBriefingKey: true)
    }

    /// Texte du point sur la journée (POST /api/briefing/ → {"text": "…"}).
    static func text() async throws -> String {
        struct TextReply: Decodable { let text: String }
        let reply: TextReply = try await client.request(
            "/api/briefing/",
            method: "POST",
            body: EmptyBody(),
            useBriefingKey: true
        )
        return reply.text
    }
}

private struct EmptyBody: Encodable {}

enum TaskService {
    static let client = APIClient()

    static func list() async throws -> [Todo] {
        try await client.request("/api/tasks/")
    }

    static func update(_ task: Todo) async throws -> Todo {
        struct Body: Encodable {
            let title: String?
            let description: String?
            let status: String?
            let expected_updated_at: String?
        }
        let body = Body(
            title: task.title,
            description: task.description,
            status: task.status,
            expected_updated_at: Self.iso(task.updatedAt)
        )
        return try await client.request("/api/tasks/\(task.id)/", method: "PATCH", body: body)
    }

    @discardableResult
    static func toggle(_ task: Todo) async throws -> Todo {
        var copy = task
        copy.status = task.isDone ? "todo" : "done"
        return try await update(copy)
    }

    static func delete(_ task: Todo) async throws {
        struct Body: Encodable { let expected_updated_at: String }
        try await client.requestNoContent("/api/tasks/\(task.id)/".trimmingCharacters(in: .whitespaces))
    }

    static func iso(_ date: Date) -> String {
        iso8601Fractional.string(from: date)
    }
}

enum MemoryService {
    static let client = APIClient()

    static func list() async throws -> [MemoryItem] {
        try await client.request("/api/memories/")
    }

    static func delete(_ memory: MemoryItem) async throws {
        try await client.requestNoContent("/api/memories/\(memory.id)/")
    }
}

enum FocusService {
    static let client = APIClient()

    private struct PhaseBody: Encodable {
        let phase: String
    }

    private struct CycleBody: Encodable {
        let cycle: Int
    }

    static func list() async throws -> [FocusSession] {
        try await client.request("/api/focus-sessions/")
    }

    static func start(durationMinutes: Int, label: String?, taskID: Int? = nil) async throws -> FocusSession {
        let body = FocusSessionCreate(durationMinutes: durationMinutes, label: label, taskID: taskID)
        return try await client.request("/api/focus-sessions/", method: "POST", body: body)
    }

    /// Transition d'horloge : "running" (départ ou reprise) ou "paused".
    /// Le serveur garde l'autorité sur le temps restant.
    static func setPhase(_ session: FocusSession, _ phase: String) async throws -> FocusSession {
        try await client.request(
            "/api/focus-sessions/\(session.id)/",
            method: "PATCH",
            body: PhaseBody(phase: phase)
        )
    }

    /// Termine la session (le serveur n'accepte que si le temps est réellement
    /// écoulé) et marque la tâche liée comme faite.
    static func complete(_ session: FocusSession) async throws -> FocusCompletionReply {
        try await client.request(
            "/api/focus-sessions/\(session.id)/complete/",
            method: "POST",
            body: EmptyBody()
        )
    }

    /// Annule le marquage de la tâche effectué par la complétion (ne marche que
    /// si le résultat enregistré est "completed" et que le cycle correspond).
    static func undo(_ session: FocusSession) async throws -> FocusCompletionReply {
        let cycle = session.completedCycle ?? 1
        return try await client.request(
            "/api/focus-sessions/\(session.id)/undo/",
            method: "POST",
            body: CycleBody(cycle: cycle)
        )
    }

    /// Remet la session à zéro (phase "idle"), sans toucher à la tâche.
    static func reset(_ session: FocusSession) async throws -> FocusSession {
        try await client.request(
            "/api/focus-sessions/\(session.id)/reset/",
            method: "POST",
            body: EmptyBody()
        )
    }

    static func delete(_ session: FocusSession) async throws {
        try await client.requestNoContent("/api/focus-sessions/\(session.id)/")
    }
}

enum ReminderService {
    static let client = APIClient()

    static func list() async throws -> [Reminder] {
        try await client.request("/api/reminders/")
    }

    static func create(_ reminder: Reminder) async throws -> Reminder {
        try await client.request("/api/reminders/", method: "POST", body: reminder)
    }

    static func update(_ reminder: Reminder) async throws -> Reminder {
        guard let id = reminder.id else { throw APIError.invalidURL }
        return try await client.request("/api/reminders/\(id)/", method: "PATCH", body: reminder)
    }

    static func delete(_ reminder: Reminder) async throws {
        guard let id = reminder.id else { throw APIError.invalidURL }
        try await client.requestNoContent("/api/reminders/\(id)/")
    }
}
