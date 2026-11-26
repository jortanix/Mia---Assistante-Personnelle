import Foundation
import UserNotifications

/// Affiche les rappels même quand l'app est ouverte : sans ce délégué, iOS
/// avale silencieusement les notifications reçues au premier plan.
final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationDelegate()

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }
}

/// Planifie des notifications locales depuis les rappels du backend.
/// Fonctionne sans APNs : la notification est planifiée sur l'appareil.
enum NotificationScheduler {
    /// À appeler au lancement, avant toute demande d'autorisation.
    static func configure() {
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
    }

    static func requestAuthorization() async -> Bool {
        let center = UNUserNotificationCenter.current()
        do {
            return try await center.requestAuthorization(options: [.alert, .sound, .badge])
        } catch {
            return false
        }
    }

    /// Remplace toutes les notifications planifiées par celles des rappels à venir.
    static func rescheduleAll(_ reminders: [Reminder]) async {
        let center = UNUserNotificationCenter.current()
        center.removeAllPendingNotificationRequests()
        let now = Date()
        for reminder in reminders where !reminder.done && reminder.dueAt > now {
            schedule(reminder)
        }
    }

    static func schedule(_ reminder: Reminder) {
        guard reminder.dueAt > Date() else { return }
        let content = UNMutableNotificationContent()
        content.title = "Mia — Rappel"
        content.body = reminder.title
        content.sound = .default

        let trigger = UNCalendarNotificationTrigger(
            dateMatching: Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute],
                from: reminder.dueAt
            ),
            repeats: reminder.repeatRule == "daily"
        )
        let identifier = "mia-reminder-\(reminder.id ?? -1)"
        let request = UNNotificationRequest(
            identifier: identifier,
            content: content,
            trigger: trigger
        )
        UNUserNotificationCenter.current().add(request)
    }
}
