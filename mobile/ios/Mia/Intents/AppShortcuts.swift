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
        return .result(dialog: IntentDialog(stringLiteral: parts.joined(separator: " ")))
    }
}

struct NewReminderIntent: AppIntent {
    static var title: LocalizedStringResource = "Créer un rappel"
    static var description = IntentDescription("Crée un rappel dans Mia et planifie la notification.")
    static var parameterSummary: some ParameterSummary {
        When(\.$date, .hasAnyValue) {
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
        NotificationScheduler.schedule(created)
        let formatted = created.dueAt.formatted(date: .abbreviated, time: .shortened)
        return .result(dialog: "Rappel « \(created.title) » notifié le \(formatted).")
    }
}

// MARK: - Réveil du matin

struct WakeUpIntent: AppIntent {
    static var title: LocalizedStringResource = "Réveil avec Mia"
    static var description = IntentDescription("Le point du matin, à déclencher sur l'arrêt de l'alarme (automation Raccourcis).")
    static var parameterSummary: some ParameterSummary {
        Summary("Réveil avec Mia")
    }

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let point = try await BriefingService.text()
        return .result(dialog: "Bonjour ! \(point)")
    }
}

// MARK: - Brainrot

struct LogBrainrotIntent: AppIntent {
    static var title: LocalizedStringResource = "Céder au brainrot"
    static var description = IntentDescription("Enregistre un cédage (app ouverte) ou une résistance ; fait évoluer le cerveau de l'onglet Brainrot.")

    @Parameter(title: "App")
    var app: String?

    @Parameter(title: "Résisté ?", default: false)
    var resisted: Bool

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let event = try await BrainrotService.log(app: app ?? "", lapsed: !resisted)
        let name = (app?.isEmpty == false) ? app! : "l'app"
        if event.lapsed {
            return .result(dialog: "Cédage noté sur \(name). Le cerveau se dégrade…")
        }
        return .result(dialog: "Bien joué : résistance sur \(name). Le cerveau te remercie.")
    }
}

// MARK: - Raccourcis proposés par l'app

struct MiaShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: AskMiaIntent(),
            phrases: [
                "Demander à \(.applicationName)",
                "Demande à \(.applicationName)",
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
                "Rappelle-moi avec \(.applicationName)",
                "Créer un rappel avec \(.applicationName)",
            ],
            shortTitle: "Créer un rappel",
            systemImageName: "bell.badge"
        )
        AppShortcut(
            intent: WakeUpIntent(),
            phrases: [
                "Réveil avec \(.applicationName)",
                "Point du matin avec \(.applicationName)",
            ],
            shortTitle: "Réveil avec Mia",
            systemImageName: "sunrise.fill"
        )
        AppShortcut(
            intent: LogBrainrotIntent(),
            phrases: [
                "Céder au brainrot avec \(.applicationName)",
                "Noter une résistance avec \(.applicationName)",
            ],
            shortTitle: "Céder au brainrot",
            systemImageName: "brain.head.profile"
        )
    }
}
