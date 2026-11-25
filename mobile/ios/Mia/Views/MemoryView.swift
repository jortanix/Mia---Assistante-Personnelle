import SwiftUI

@MainActor
final class MemoryViewModel: ObservableObject {
    @Published var memories: [MemoryItem] = []
    @Published var isLoading = false
    @Published var errorText: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            memories = try await MemoryService.list()
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    func delete(_ memory: MemoryItem) {
        Task {
            do {
                try await MemoryService.delete(memory)
                memories.removeAll { $0.id == memory.id }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}

struct MemoryView: View {
    @StateObject private var model = MemoryViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.memories.isEmpty {
                    ProgressView()
                } else if let error = model.errorText, model.memories.isEmpty {
                    ContentUnavailableView {
                        Label("Impossible de charger", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Réessayer") { Task { await model.load() } }
                    }
                } else if model.memories.isEmpty {
                    ContentUnavailableView {
                        Label("Aucune préférence mémorisée", systemImage: "brain")
                    } description: {
                        Text("Quand tu confirmes une proposition de Mia dans le chat, elle est retenue ici.")
                    }
                } else {
                    List {
                        ForEach(model.memories) { memory in
                            VStack(alignment: .leading, spacing: 4) {
                                Text(memory.content)
                                Text("Retenue le " + memory.confirmedAt.formatted(date: .abbreviated, time: .shortened))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .swipeActions {
                                Button(role: .destructive) { model.delete(memory) } label: {
                                    Label("Oublier", systemImage: "trash")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Mémoire")
            .refreshable { await model.load() }
            .task { await model.load() }
        }
    }
}
