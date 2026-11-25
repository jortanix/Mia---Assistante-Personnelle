import SwiftUI

// MARK: - ViewModel

@MainActor
final class BrainrotViewModel: ObservableObject {
    @Published var events: [BrainrotEvent] = []
    @Published var isLoading = false
    @Published var errorText: String?

    /// Événements du jour (c'est eux qui font baisser le score).
    var todayEvents: [BrainrotEvent] {
        events.filter { Calendar.current.isDateInToday($0.createdAt) }
    }

    var fallsToday: Int { todayEvents.filter(\.lapsed).count }
    var resistsToday: Int { todayEvents.filter { !$0.lapsed }.count }

    /// Santé du cerveau 0-100 : chaque cédage enlève 15, chaque résistance
    /// rend 5 — plafonné à 100 le matin.
    var health: Int {
        max(0, min(100, 100 - 15 * fallsToday + 5 * resistsToday))
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            events = try await BrainrotService.list()
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    func log(app: String, lapsed: Bool) {
        Task {
            do {
                let event = try await BrainrotService.log(app: app, lapsed: lapsed)
                events.insert(event, at: 0)
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    func delete(_ event: BrainrotEvent) {
        Task {
            do {
                try await BrainrotService.delete(event)
                events.removeAll { $0.id == event.id }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}

// MARK: - Vue

struct BrainrotView: View {
    @StateObject private var model = BrainrotViewModel()
    @State private var showNewEventSheet = false

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.events.isEmpty {
                    ProgressView()
                } else if let error = model.errorText, model.events.isEmpty {
                    ContentUnavailableView {
                        Label("Impossible de charger", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Réessayer") { Task { await model.load() } }
                    }
                } else if model.events.isEmpty {
                    ContentUnavailableView {
                        Label("Aucun cédage pour l'instant", systemImage: "brain.head.profile")
                    } description: {
                        Text("Chaque app distrayante que tu ouvres malgré tout fait pourrir un peu plus le cerveau — chaque résistance le soigne.")
                    } actions: {
                        Button("Enregistrer un cédage") { showNewEventSheet = true }
                    }
                } else {
                    List {
                        Section {
                            brainCard
                                .frame(maxWidth: .infinity)
                                .listRowBackground(Color.clear)
                        }

                        Section(model.todayEvents.isEmpty ? "Aujourd'hui — rien à signaler 🎉" : "Cédages du jour") {
                            if model.todayEvents.isEmpty {
                                Text("Le cerveau est intact aujourd'hui.")
                                    .foregroundStyle(.secondary)
                            } else {
                                ForEach(model.todayEvents) { event in
                                    eventRow(event)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Brainrot")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showNewEventSheet = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Enregistrer un cédage")
                }
            }
            .sheet(isPresented: $showNewEventSheet) {
                NewLapseSheet { app, lapsed in
                    model.log(app: app, lapsed: lapsed)
                }
            }
            .refreshable { await model.load() }
            .task { await model.load() }
        }
    }

    // MARK: Santé du cerveau

    private var healthColor: Color {
        switch model.health {
        case 66...: .green
        case 33..<66: .orange
        default: .red
        }
    }

    private var healthLabel: String {
        switch model.health {
        case 66...: "Cerveau en forme"
        case 33..<66: "Cerveau fragile"
        default: "Cerveau en perfusion"
        }
    }

    private var brainCard: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .stroke(healthColor.opacity(0.2), lineWidth: 12)
                    .frame(width: 140, height: 140)
                Circle()
                    .trim(from: 0, to: CGFloat(model.health) / 100)
                    .stroke(healthColor, style: StrokeStyle(lineWidth: 12, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .frame(width: 140, height: 140)
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 48))
                    .foregroundStyle(healthColor)
            }
            Text("\(model.health)%")
                .font(.title2.bold())
                .foregroundStyle(healthColor)
            Text(healthLabel)
                .font(.headline)
                .foregroundStyle(.primary)
            Text("\(model.fallsToday) cédage\(model.fallsToday > 1 ? "s" : "") · \(model.resistsToday) résistance\(model.resistsToday > 1 ? "s" : "")")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
    }

    private func eventRow(_ event: BrainrotEvent) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(event.app.isEmpty ? "App non précisée" : event.app)
                    .font(.body)
                Text(event.createdAt.formatted(date: .omitted, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(event.lapsed ? "Cédé" : "Résisté")
                .font(.caption.bold())
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(event.lapsed ? Color.red.opacity(0.12) : Color.green.opacity(0.12))
                .foregroundStyle(event.lapsed ? .red : .green)
                .clipShape(Capsule())
        }
        .swipeActions {
            Button(role: .destructive) { model.delete(event) } label: {
                Label("Supprimer", systemImage: "trash")
            }
        }
    }
}

// MARK: - Feuille de saisie

struct NewLapseSheet: View {
    @Environment(\.dismiss) private var dismiss
    let onSave: (String, Bool) -> Void

    private let suggestions = ["TikTok", "Instagram", "YouTube", "X", "Threads"]

    @State private var appName = ""
    @State private var lapsed = true

    var body: some View {
        NavigationStack {
            Form {
                Section("Quelle app ?") {
                    TextField("Ex. TikTok", text: $appName)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(suggestions, id: \.self) { suggestion in
                                Button(suggestion) { appName = suggestion }
                                    .buttonStyle(.bordered)
                                    .tint(appName == suggestion ? .accentColor : .secondary)
                            }
                        }
                    }
                }
                Section("Verdict") {
                    Picker("Verdict", selection: $lapsed) {
                        Text("J'ai cédé 💀").tag(true)
                        Text("J'ai résisté 🧠").tag(false)
                    }
                    .pickerStyle(.segmented)
                }
            }
            .navigationTitle("Cédage")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Enregistrer") {
                        onSave(appName.trimmingCharacters(in: .whitespaces), lapsed)
                        dismiss()
                    }
                    .disabled(appName.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
