import SwiftUI

@main
struct MiaApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            RootTabView()
        }
    }
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        NotificationScheduler.configure()
        Task { await NotificationScheduler.requestAuthorization() }
        return true
    }
}

struct RootTabView: View {
    var body: some View {
        TabView {
            ChatView()
                .tabItem { Label("Discuter", systemImage: "bubble.left.and.bubble.right") }
            BriefingView()
                .tabItem { Label("Journée", systemImage: "calendar") }
            TasksView()
                .tabItem { Label("Tâches", systemImage: "checklist") }
            FocusView()
                .tabItem { Label("Concentration", systemImage: "timer") }
            BrainrotView()
                .tabItem { Label("Brainrot", systemImage: "brain.head.profile") }
            MemoryView()
                .tabItem { Label("Mémoire", systemImage: "brain") }
            RemindersView()
                .tabItem { Label("Rappels", systemImage: "bell") }
            SettingsView()
                .tabItem { Label("Réglages", systemImage: "gearshape") }
        }
    }
}
