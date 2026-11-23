import AppIntents
import Foundation

// MARK: - « Hey Siri, … » / App Shortcuts
// Apple ne permet pas de remplacer Hey Siri ; Mia s'enregistre comme
// App Intents : Siri transcrit la question, Mia répond, Siri lit la réponse.
// Les mêmes intents sont des raccourcis réutilisables.

struct AskMiaIntent: AppIntent {
    static var title: LocalizedStringResource = "Demander à Mia"
    static var description = IntentDescription("Pose une question à Mia et entends sa réponse.")
    static var parameterSummary: some ParameterSummary {
        Summary("Demander à Mia \(\.$question)")
    }

    @Parameter(title: "Question")
    var question: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let reply = try await ChatService.ask(question)
        return .result(dialog: "Mia : \(reply)")
    }
}

struct BriefingIntent: AppIntent {
    static var title: LocalizedStringResource = "Point sur la journée"
    static var description = IntentDescription("Résumé concis de ton agenda et de tes mails iCloud.")
    static var parameterSummary: some ParameterSummary {
        Summary("Point sur la journée")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let briefing = try await BriefingService.today()
        var parts: [String] = []

        switch briefing.calendar.status {
        case "ok":
            if briefing.calendar.events.isEmpty {
                parts.append("Aucun rendez-vous aujourd'hui.")
            } else {
                let n = briefing.calendar.events.count
                let summaries = briefing.calendar.events
                    .prefix(3)
                    .map { $0.summary }
                    .joined(separator: ", ")
                parts.append(n <= 3
                    ? "Ton agenda : \(summaries)."
                    : "\(n) événements, notamment \(summaries).")
            }
        case "not_configured":
            parts.append("L'agenda n'est pas configuré.")
        default:
            parts.append("L'agenda est indisponible.")
        }

        switch briefing.emails.status {
        case "ok":
            let unread = briefing.emails.messages.filter { $0.unread == true }.count
            parts.append(unread == 0
                ? "Aucun mail non lu."
                : "\(unread) mail\(unread > 1 ? "s" : "") non lu\(unread > 1 ? "s" : "").")
        case "not_configured":
            parts.append("Les mails ne sont pas configurés.")
        default:
            parts.append("Les mails sont indisponibles.")
        }

        if briefing.partial {
            parts.append("Ce point est partiel.")
        }
        return .result(dialog: parts.joined(separator: " "))
    }
}

struct NewReminderIntent: AppIntent {
    static var title: LocalizedStringResource = "Créer un rappel"
    static var description = IntentDescription("Crée un rappel dans Mia et planifie la notification.")
    static var parameterSummary: some ParameterSummary {
        When(\.$date) {
            Summary("Créer un rappel \(\.$title) à \(\.$date)")
        } otherwise: {
            Summary("Créer un rappel \(\.$title) dans une heure")
        }
    }

    @Parameter(title: "Titre")
    var title: String

    @Parameter(title: "Date et heure")
    var date: Date?

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let due = date ?? Date().addingTimeInterval(3600)
        let created = try await ReminderService.create(
            Reminder(id: nil, title: title, dueAt: due, done: false, repeatRule: "none", createdAt: nil, updatedAt: nil)
        )
        await NotificationScheduler.schedule(created)
        let formatted = created.dueAt.formatted(date: .abbreviated, time: .shortened)
        return .result(dialog: "Rappel « \(created.title) » notifié le \(formatted).")
    }
}

// MARK: - Raccourcis proposés par l'app

struct MiaShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskMiaIntent(),
            phrases: [
                "Demander à \(.applicationName)",
                "Demande à \(.applicationName) \(\.$question)",
            ],
            shortTitle: "Demander à Mia",
            systemImageName: "bubble.left.and.bubble.right"
        )
        AppShortcut(
            intent: BriefingIntent(),
            phrases: [
                "Point sur la journée avec \(.applicationName)",
                "Résume ma journée avec \(.applicationName)",
            ],
            shortTitle: "Point sur la journée",
            systemImageName: "calendar.badge.clock"
        )
        AppShortcut(
            intent: NewReminderIntent(),
            phrases: [
                "Rappelle-moi \(\.$title) avec \(.applicationName)",
                "Créer un rappel \(\.$title) à \(\.$date)",
            ],
            shortTitle: "Créer un rappel",
            systemImageName: "bell.badge"
        )
    }
}
