import Foundation

// MARK: - Décodage ISO 8601 (y compris secondes fractionnaires)

private let iso8601Plain: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    return f
}()

private let iso8601Fractional: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

/// Décodeur partagé : dates ISO 8601 avec ou sans fraction de seconde (Django
/// émet souvent des microsecondes, ex. ``...23.456789Z``).
extension JSONDecoder {
    static func mia() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = iso8601Fractional.date(from: string) ?? iso8601Plain.date(from: string) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Date ISO 8601 invalide : \(string)"
            )
        }
        return decoder
    }
}

extension JSONEncoder {
    static func mia() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(iso8601Fractional.string(from: date))
        }
        return encoder
    }
}

// MARK: - Chat

struct ChatRequest: Codable {
    let message: String
    let conversationID: Int?
    let useMemory: Bool?

    enum CodingKeys: String, CodingKey {
        case message, conversationID = "conversation_id", useMemory = "use_memory"
    }
}

struct ChatReply: Codable {
    let conversationID: Int?
    let reply: String?
    let actionProposal: ActionProposal?

    enum CodingKeys: String, CodingKey {
        case conversationID = "conversation_id", reply, actionProposal = "action_proposal"
    }
}

/// Événement NDJSON du chat streamé.
struct StreamEvent: Codable {
    let type: String
    let conversationID: Int?
    let content: String?
    let message: String?
    let actionProposal: ActionProposal?

    enum CodingKeys: String, CodingKey {
        case type, content, message
        case conversationID = "conversation_id"
        case actionProposal = "action_proposal"
    }
}

struct ActionProposal: Codable, Identifiable {
    let id: Int
    let assistantMessageID: Int
    let action: String
    let data: ActionProposalData?
    let status: String
    let task: Task?
    let created: Date

    enum CodingKeys: String, CodingKey {
        case id, action, status, task
        case assistantMessageID = "assistant_message_id"
        case data
        case created = "created_at"
    }
}

struct ActionProposalData: Codable {
    let title: String?
    let description: String?
    let content: String?
}

// MARK: - Tâches

struct Task: Codable, Identifiable, Equatable {
    let id: Int
    var title: String
    var description: String
    var status: String
    let createdAt: Date
    var updatedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, title, description, status
        case createdAt = "created_at", updatedAt = "updated_at"
    }

    var isDone: Bool { status == "done" }
}

// MARK: - Mémoire

struct MemoryItem: Codable, Identifiable {
    let id: Int
    let content: String
    let confirmedAt: Date

    enum CodingKeys: String, CodingKey {
        case id, content, confirmedAt = "confirmed_at"
    }
}

// MARK: - Briefing

struct Briefing: Codable {
    let day: String
    let timezone: String
    let generatedAt: Date
    let calendar: CalendarSource
    let emails: EmailSource
    let partial: Bool

    enum CodingKeys: String, CodingKey {
        case day, timezone, calendar, emails, partial
        case generatedAt = "generated_at"
    }
}

struct CalendarSource: Codable {
    let status: String
    let events: [CalendarEvent]
}

struct CalendarEvent: Codable, Identifiable {
    let id: String
    let summary: String
    let description: String?
    let location: String?
    let allDay: Bool
    let start: Date?
    let end: Date?
    let calendar: String?

    enum CodingKeys: String, CodingKey {
        case id, summary, description, location, allDay = "all_day", start, end, calendar
    }
}

struct EmailSource: Codable {
    let status: String
    let messages: [EmailMessage]
}

struct EmailMessage: Codable, Identifiable {
    let id: String
    let subject: String
    let from: String?
    let date: Date?
    let body: String?
    let unread: Bool?
}

// MARK: - Sessions de concentration

struct FocusSession: Codable, Identifiable {
    let id: Int
    let durationMinutes: Int
    let label: String?
    let phase: String
    let deadline: Date?
    let remainingTimeMS: Int?
    let outcome: String?
    let completedAt: Date?
    let cycle: Int?
    let completedCycle: Int?
    let task: Task?

    enum CodingKeys: String, CodingKey {
        case id, phase, deadline, outcome, cycle, task
        case durationMinutes = "duration_minutes"
        case label
        case remainingTimeMS = "remaining_time_ms"
        case completedAt = "completed_at"
        case completedCycle = "completed_cycle"
    }
}

struct FocusSessionCreate: Codable {
    let durationMinutes: Int
    let label: String?

    enum CodingKeys: String, CodingKey {
        case durationMinutes = "duration_minutes", label
    }
}

// MARK: - Rappels

struct Reminder: Codable, Identifiable, Equatable {
    let id: Int?
    var title: String
    var dueAt: Date
    var done: Bool
    var repeatRule: String
    let createdAt: Date?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, title, done
        case dueAt = "due_at"
        case repeatRule = "repeat"
        case createdAt = "created_at", updatedAt = "updated_at"
    }
}
