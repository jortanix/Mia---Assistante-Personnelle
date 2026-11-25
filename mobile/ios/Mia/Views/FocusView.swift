import SwiftUI

@MainActor
final class FocusViewModel: ObservableObject {
    @Published var sessions: [FocusSession] = []
    @Published var isLoading = false
    @Published var errorText: String?
    @Published var alertText: String?
    @Published var showCreateSheet = false

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            sessions = try await FocusService.list()
                .sorted { ($0.createdAt ?? .distantPast) > ($1.createdAt ?? .distantPast) }
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    /// Étale une erreur d'action en alerte (alors que errorText sert à l'état vide).
    private func fail(_ error: Error) {
        alertText = error.localizedDescription
    }

    private func replace(_ updated: FocusSession) {
        if let idx = sessions.firstIndex(where: { $0.id == updated.id }) {
            sessions[idx] = updated
        } else {
            sessions.insert(updated, at: 0)
        }
    }

    func create(duration: Int, label: String, taskID: Int?) {
        Task {
            do {
                let created = try await FocusService.start(
                    durationMinutes: duration,
                    label: label.trimmingCharacters(in: .whitespaces).isEmpty ? nil : label,
                    taskID: taskID
                )
                replace(created)
                showCreateSheet = false
            } catch {
                fail(error)
            }
        }
    }

    func start(_ session: FocusSession) { apply(session) { try await FocusService.setPhase($0, "running") } }
    func pause(_ session: FocusSession) { apply(session) { try await FocusService.setPhase($0, "paused") } }
    func resume(_ session: FocusSession) { apply(session) { try await FocusService.setPhase($0, "running") } }
    func reset(_ session: FocusSession) { apply(session) { try await FocusService.reset($0) } }

    func complete(_ session: FocusSession) {
        Task {
            do {
                let reply = try await FocusService.complete(session)
                if reply.message != "Session terminée." { alertText = reply.message }
                await reload()
            } catch {
                fail(error)
            }
        }
    }

    func undo(_ session: FocusSession) {
        Task {
            do {
                _ = try await FocusService.undo(session)
                await reload()
            } catch {
                fail(error)
            }
        }
    }

    func delete(_ session: FocusSession) {
        Task {
            do {
                try await FocusService.delete(session)
                sessions.removeAll { $0.id == session.id }
            } catch {
                fail(error)
            }
        }
    }

    private func apply(_ session: FocusSession, _ op: (FocusSession) async throws -> FocusSession) {
        Task {
            do {
                let updated = try await op(session)
                replace(updated)
            } catch {
                fail(error)
            }
        }
    }

    private func reload() async {
        do {
            sessions = try await FocusService.list()
                .sorted { ($0.createdAt ?? .distantPast) > ($1.createdAt ?? .distantPast) }
            errorText = nil
        } catch {
            // Un rechargement après une complétion ne doit pas masquer le
            // résultat : on conserve la liste locale en cas d'échec réseau.
            alertText = error.localizedDescription
        }
    }
}

struct FocusView: View {
    @StateObject private var model = FocusViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.sessions.isEmpty {
                    ProgressView()
                } else if let error = model.errorText, model.sessions.isEmpty {
                    ContentUnavailableView {
                        Label("Impossible de charger", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Réessayer") { Task { await model.load() } }
                    }
                } else if model.sessions.isEmpty {
                    ContentUnavailableView {
                        Label("Aucune session", systemImage: "timer")
                    } description: {
                        Text("Lance une session de concentration pour rester focus.")
                    } actions: {
                        Button("Nouvelle session") { model.showCreateSheet = true }
                            .buttonStyle(.borderedProminent)
                    }
                } else {
                    List {
                        ForEach(model.sessions) { session in
                            FocusRow(session: session, model: model)
                                .listRowInsets(EdgeInsets(top: 10, leading: 16, bottom: 10, trailing: 16))
                                .swipeActions {
                                    Button(role: .destructive) { model.delete(session) } label: {
                                        Label("Supprimer", systemImage: "trash")
                                    }
                                }
                        }
                    }
                }
            }
            .navigationTitle("Concentration")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { model.showCreateSheet = true } label: { Image(systemName: "plus") }
                }
            }
            .sheet(isPresented: $model.showCreateSheet) {
                NewFocusSheet { duration, label, taskID in
                    model.create(duration: duration, label: label, taskID: taskID)
                }
            }
            .alert("Erreur", isPresented: Binding(
                get: { model.alertText != nil },
                set: { if !$0 { model.alertText = nil } }
            )) {
                Button("OK", role: .cancel) { model.alertText = nil }
            } message: {
                Text(model.alertText ?? "")
            }
            .refreshable { await model.load() }
            .task { await model.load() }
        }
    }
}

/// Ligne d'une session : décompte en direct (mise à jour chaque seconde) et
/// contrôles selon la phase.
struct FocusRow: View {
    let session: FocusSession
    let model: FocusViewModel

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            rowContent(now: context.date)
        }
    }

    private func rowContent(now: Date) -> some View {
        let total = Double(session.durationMinutes * 60)
        let remaining = FocusRow.remaining(session, now: now)
        let progress = FocusRow.progress(remaining: remaining, total: total)

        return HStack(alignment: .center, spacing: 16) {
            ZStack {
                Circle()
                    .stroke(Color.secondary.opacity(0.2), lineWidth: 6)
                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(AngularGradient(
                        gradient: Gradient(colors: [.blue, .mint]),
                        center: .center
                    ), style: StrokeStyle(lineWidth: 6, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                VStack(spacing: 1) {
                    Text(FocusRow.format(remaining))
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                    Text(session.phaseLabel)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(width: 76, height: 76)
            .padding(4)

            VStack(alignment: .leading, spacing: 4) {
                Text(session.label?.nilIfEmpty ?? "Session de concentration")
                    .font(.headline)
                    .lineLimit(1)
                if let task = session.task {
                    Label {
                        Text(task.title)
                            .lineLimit(1)
                            .strikethrough(task.isDone)
                    } icon: {
                        Image(systemName: task.isDone ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(task.isDone ? .green : .secondary)
                    }
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                }
                Text("\(session.durationMinutes) min" + (session.task != nil ? "" : " · sans tâche"))
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                controls(remaining: remaining)
                    .padding(.top, 2)
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func controls(remaining: TimeInterval) -> some View {
        HStack(spacing: 8) {
            switch session.phase {
            case "idle":
                button("play.fill", "Démarrer") { model.start(session) }
            case "running":
                button("pause.fill", "Pause") { model.pause(session) }
                Button {
                    model.complete(session)
                } label: {
                    Label("Terminer", systemImage: "flag.checkered")
                        .labelStyle(.titleAndIcon)
                }
                .buttonStyle(.bordered)
                .disabled(remaining > 0.5)
            case "paused":
                button("play.fill", "Reprendre") { model.resume(session) }
                button("arrow.counterclockwise", "Réinitialiser") { model.reset(session) }
                Button {
                    model.complete(session)
                } label: {
                    Label("Terminer", systemImage: "flag.checkered")
                        .labelStyle(.titleAndIcon)
                }
                .buttonStyle(.bordered)
                .disabled(remaining > 0.5)
            case "finished":
                if session.outcome == "completed" {
                    button("arrow.uturn.backward", "Annuler") { model.undo(session) }
                }
                outcomeBadge
            default:
                EmptyView()
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
    }

    private func button(_ icon: String, _ title: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .labelStyle(.titleAndIcon)
        }
    }

    private var outcomeBadge: some View {
        Group {
            switch session.outcome {
            case "completed":
                Text("✓ Tâche faite").foregroundStyle(.green).font(.caption.bold())
            case "already_done":
                Text("Déjà faite").font(.caption).foregroundStyle(.secondary)
            case "undone":
                Text("Marquage annulé").font(.caption).foregroundStyle(.secondary)
            default:
                Text("Terminée").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Calculs

    static func remaining(_ session: FocusSession, now: Date) -> TimeInterval {
        switch session.phase {
        case "running":
            guard let deadline = session.deadline else { return Double(session.durationMinutes * 60) }
            return max(0, deadline.timeIntervalSince(now))
        case "paused":
            guard let ms = session.remainingTimeMS else { return Double(session.durationMinutes * 60) }
            return Double(ms) / 1000
        case "finished":
            return 0
        default:
            return Double(session.durationMinutes * 60)
        }
    }

    static func progress(remaining: TimeInterval, total: TimeInterval) -> Double {
        guard total > 0 else { return 0 }
        return min(1, max(0, 1 - remaining / total))
    }

    static func format(_ seconds: TimeInterval) -> String {
        let s = Int(seconds.rounded())
        let h = s / 3600
        let m = (s % 3600) / 60
        let sec = s % 60
        return h > 0
            ? String(format: "%d:%02d:%02d", h, m, sec)
            : String(format: "%02d:%02d", m, sec)
    }
}

extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}

extension FocusSession {
    /// Libellé de phase pour l'affichage (à côté du décompte).
    var phaseLabel: String {
        switch phase {
        case "running": return "en cours"
        case "paused": return "pause"
        case "finished": return "terminée"
        default: return "prête"
        }
    }
}

/// Feuille de création : durée, intitulé (optionnel), tâche liée (optionnelle,
/// uniquement les tâches à faire).
struct NewFocusSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var duration = 25
    @State private var label = ""
    @State private var selectedTaskID: Int?
    @State private var tasks: [Todo] = []
    @State private var tasksError = false

    let onCreate: (Int, String, Int?) -> Void

    private let durations = [10, 15, 25, 50, 90]

    var body: some View {
        NavigationStack {
            Form {
                Section("Durée") {
                    Picker("Durée", selection: $duration) {
                        ForEach(durations, id: \.self) { d in
                            Text("\(d) min").tag(d)
                        }
                    }
                    .pickerStyle(.segmented)
                }
                Section("Intitulé (optionnel)") {
                    TextField("Ex. : ranger mon bureau", text: $label)
                }
                Section("Tâche liée (optionnel)") {
                    if tasksError {
                        Text("Impossible de charger les tâches.")
                            .foregroundStyle(.secondary)
                    } else {
                        Picker("Tâche", selection: $selectedTaskID) {
                            Text("Aucune").tag(Int?.none)
                            ForEach(tasks) { task in
                                Text(task.title).tag(Int?.some(task.id))
                            }
                        }
                    }
                }
            }
            .navigationTitle("Nouvelle session")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Créer") {
                        onCreate(duration, label, selectedTaskID)
                        dismiss()
                    }
                }
            }
            .task {
                do {
                    tasks = try await TaskService.list().filter { !$0.isDone }
                    tasksError = false
                } catch {
                    tasksError = true
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
