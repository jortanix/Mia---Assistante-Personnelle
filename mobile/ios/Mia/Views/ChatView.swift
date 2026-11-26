import Combine
import SwiftUI

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: String // "user" | "mia"
    var content: String
}

/// Proposition de rappel en attente de confirmation dans le chat.
struct PendingReminder {
    var title: String
    var dueAt: Date
    let whenHint: String
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isBusy = false
    @Published var errorText: String?
    @Published var draft = ""
    /// Proposition de rappel à confirmer (carte sous la conversation).
    @Published var pendingReminder: PendingReminder?
    @Published var isScheduling = false

    let dictation = DictationManager()
    private var cancellables: Set<AnyCancellable> = []

    init() {
        // Re-publie les changements de la dictée pour que la vue se mette à jour.
        dictation.objectWillChange
            .sink { [weak self] _ in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }

    var isInputDisabled: Bool { isBusy }

    func send() {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isBusy else { return }
        draft = ""
        errorText = nil
        messages.append(ChatMessage(role: "user", content: text))
        messages.append(ChatMessage(role: "mia", content: ""))
        isBusy = true
        let index = messages.index(before: messages.endIndex)

        Task {
            do {
                let full = try await ChatService.stream(text) { [weak self] event in
                    // Le stream NDJSON arrive sur une queue de fond : on bascule
                    // sur le MainActor pour mettre à jour l'état publié.
                    Task { @MainActor in
                        self?.onStreamEvent(event, updating: index)
                    }
                }
                if full.isEmpty {
                    self.messages[index].content = "Aucune réponse."
                }
            } catch {
                self.messages[index].content = "⚠︎ \(error.localizedDescription)"
            }
            self.isBusy = false
        }
    }

    private func onStreamEvent(_ event: StreamEvent, updating index: Int) {
        switch event.type {
        case "delta":
            messages[index].content += event.content ?? ""
        case "error":
            messages[index].content = "⚠︎ \(event.message ?? "Erreur inconnue")"
        case "done":
            if let proposal = event.actionProposal {
                switch proposal.action {
                case "create_task":
                    messages[index].content +=
                        "\n\n→ Proposition : créer la tâche « \(proposal.data?.title ?? "?") ». Disponible dans l'onglet Tâches."
                case "create_reminder":
                    presentReminderProposal(proposal, at: index)
                default:
                    break
                }
            }
        default:
            break
        }
    }

    /// Affiche la carte de rappel pré-remplie par le titre et l'expression de
    /// temps bruts du backend (« dans 1 heure », « à 18h », « demain à 9h »).
    private func presentReminderProposal(_ proposal: ActionProposal, at index: Int) {
        let title = (proposal.data?.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let hint = proposal.data?.when ?? ""
        let due = ReminderWhen.parse(hint) ?? Date().addingTimeInterval(3600)
        pendingReminder = PendingReminder(title: title, dueAt: due, whenHint: hint)
        messages[index].content +=
            "\n\n📌 Je te propose un rappel : « \(title) » — vérifie l'horaire puis programme-le."
    }

    /// Crée le rappel (transforme la proposition en rappel réel côté serveur)
    /// puis planifie la notification locale. N'utilise volontairement pas
    /// `rescheduleAll` pour ne pas effacer les notifications déjà en attente.
    func confirmReminder() {
        guard let pending = pendingReminder, !isScheduling else { return }
        let title = pending.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            errorText = "Précise ce que je dois te rappeler."
            return
        }
        isScheduling = true
        Task {
            defer { isScheduling = false }
            do {
                guard await NotificationScheduler.requestAuthorization() else {
                    errorText = "Autorisation des notifications refusée. Active-la dans Réglages > Notifications."
                    return
                }
                let created = try await ReminderService.create(
                    Reminder(id: nil, title: title, dueAt: pending.dueAt, done: false,
                             repeatRule: "none", createdAt: nil, updatedAt: nil)
                )
                NotificationScheduler.schedule(created)
                pendingReminder = nil
                messages.append(ChatMessage(
                    role: "mia",
                    content: "✅ Rappel programmé : « \(created.title) » \(created.dueAt.formatted(date: .abbreviated, time: .shortened))."
                ))
            } catch {
                errorText = "Impossible de créer le rappel : \(error.localizedDescription)"
            }
        }
    }

    func cancelReminder() {
        pendingReminder = nil
    }

    func updatePendingReminder(title: String? = nil, due: Date? = nil) {
        guard var pending = pendingReminder else { return }
        if let title { pending.title = title }
        if let due { pending.dueAt = due }
        pendingReminder = pending
    }

    func startDictation() {
        Task {
            let ok = await DictationManager.requestAuthorization()
            guard ok else {
                errorText = "Autorisation micro / reconnaissance vocale refusée."
                return
            }
            dictation.onFinalText = { [weak self] text in
                guard let self else { return }
                self.draft = text
            }
            dictation.start()
        }
    }
}

struct ChatView: View {
    @StateObject private var model = ChatViewModel()
    @FocusState private var inputFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if model.messages.isEmpty {
                                welcomeCard
                            }
                            ForEach(Array(model.messages.enumerated()), id: \.element.id) { index, message in
                                bubble(message, index: index)
                            }
                        }
                        .padding()
                    }
                    .onChange(of: model.messages.count) { _, _ in
                        guard let last = model.messages.last else { return }
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                    // Un geste de scroll replie le clavier.
                    .scrollDismissesKeyboard(.immediately)
                }

                if let error = model.errorText {
                    Text(error).font(.footnote).foregroundStyle(.red).padding(.horizontal)
                }

                if model.pendingReminder != nil {
                    reminderCard
                        .padding(.horizontal)
                        .padding(.bottom, 4)
                }

                inputBar
            }
            .navigationTitle("Mia")
            .navigationBarTitleDisplayMode(.inline)
            // Bouton de repli du clavier, visible au-dessus du clavier.
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button {
                        inputFocused = false
                    } label: {
                        Image(systemName: "keyboard.chevron.compact.down")
                    }
                    .accessibilityLabel("Fermer le clavier")
                }
            }
        }
    }

    private var welcomeCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Bonjour 👋").font(.title3.bold())
            Text("Demande-moi le point sur ta journée, une tâche, une question… Je me souviens de tes préférences et je me connecte à ton agenda et tes mails iCloud.")
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.accentColor.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
    }

    private func bubble(_ message: ChatMessage, index: Int) -> some View {
        HStack {
            if message.role == "user" { Spacer(minLength: 48) }
            Text(message.content)
                .padding(12)
                .background(
                    message.role == "user" ? Color.accentColor : Color(.secondarySystemBackground),
                    in: RoundedRectangle(cornerRadius: 14)
                )
                .foregroundStyle(message.role == "user" ? .white : .primary)
                .textSelection(.enabled)
            if message.role == "mia" { Spacer(minLength: 48) }
        }
        .id(message.id)
    }

    private var reminderCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Rappel proposé", systemImage: "bell.badge")
                .font(.subheadline.bold())
                .accessibilityAddTraits(.isHeader)

            if let hint = model.pendingReminder?.whenHint, !hint.isEmpty {
                Text("Détecté : « \(hint) »")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            TextField("Que dois-je te rappeler ?", text: Binding(
                get: { model.pendingReminder?.title ?? "" },
                set: { model.updatePendingReminder(title: $0) }
            ))
            .textFieldStyle(.roundedBorder)
            .disabled(model.isScheduling)

            DatePicker(
                "Quand",
                selection: Binding(
                    get: { model.pendingReminder?.dueAt ?? Date() },
                    set: { model.updatePendingReminder(due: $0) }
                ),
                displayedComponents: [.date, .hourAndMinute]
            )
            .disabled(model.isScheduling)

            HStack {
                Button("Annuler", role: .cancel) { model.cancelReminder() }
                    .disabled(model.isScheduling)
                Spacer()
                Button {
                    model.confirmReminder()
                } label: {
                    if model.isScheduling {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Programmer")
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 14))
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            Button {
                model.startDictation()
            } label: {
                Image(systemName: model.dictation.isRecording ? "waveform" : "mic")
                    .font(.title3)
            }
            .disabled(model.isBusy)

            TextField("Écris à Mia…", text: $model.draft, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...4)
                .focused($inputFocused)
                .onSubmit { model.send() }

            Button {
                model.send()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title)
            }
            .disabled(model.isInputDisabled || model.draft.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding()
        .background(.bar)
    }
}
