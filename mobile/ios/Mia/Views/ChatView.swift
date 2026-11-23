import Combine
import SwiftUI

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: String // "user" | "mia"
    var content: String
}

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isBusy = false
    @Published var errorText: String?
    @Published var draft = ""

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
                messages[index].content +=
                    "\n\n→ Proposition : créer la tâche « \(proposal.data?.title ?? "?" ) ». Disponible dans l'onglet Tâches."
            }
        default:
            break
        }
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
                }

                if let error = model.errorText {
                    Text(error).font(.footnote).foregroundStyle(.red).padding(.horizontal)
                }

                inputBar
            }
            .navigationTitle("Mia")
            .navigationBarTitleDisplayMode(.inline)
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
