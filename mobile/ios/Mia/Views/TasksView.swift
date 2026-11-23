import SwiftUI

@MainActor
final class TasksViewModel: ObservableObject {
    @Published var tasks: [Task] = []
    @Published var isLoading = false
    @Published var errorText: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            tasks = try await TaskService.list()
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    func toggle(_ task: Task) {
        Task {
            do {
                let updated = try await TaskService.toggle(task)
                if let idx = tasks.firstIndex(where: { $0.id == updated.id }) {
                    tasks[idx] = updated
                }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    func delete(_ task: Task) {
        Task {
            do {
                try await TaskService.delete(task)
                tasks.removeAll { $0.id == task.id }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}

struct TasksView: View {
    @StateObject private var model = TasksViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.tasks.isEmpty {
                    ProgressView()
                } else if let error = model.errorText, model.tasks.isEmpty {
                    VStack {
                        Text(error).foregroundStyle(.red)
                        Button("Réessayer") { Task { await model.load() } }
                    }
                } else {
                    List {
                        ForEach(model.tasks) { task in
                            HStack(alignment: .top, spacing: 12) {
                                Button {
                                    model.toggle(task)
                                } label: {
                                    Image(systemName: task.isDone ? "checkmark.circle.fill" : "circle")
                                        .font(.title3)
                                }
                                .buttonStyle(.plain)

                                VStack(alignment: .leading, spacing: 3) {
                                    Text(task.title)
                                        .strikethrough(task.isDone)
                                        .foregroundStyle(task.isDone ? .secondary : .primary)
                                    if !task.description.isEmpty {
                                        Text(task.description).font(.footnote).foregroundStyle(.secondary)
                                    }
                                    Text(task.updatedAt.formatted(date: .abbreviated, time: .shortened))
                                        .font(.caption2).foregroundStyle(.tertiary)
                                }
                                Spacer()
                            }
                            .swipeActions {
                                Button(role: .destructive) { model.delete(task) } label: {
                                    Label("Supprimer", systemImage: "trash")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Tâches")
            .refreshable { await model.load() }
            .task { await model.load() }
            .overlay(alignment: .bottom) {
                Text("Les tâches se créent par le chat (« ajoute une tâche… »).")
                    .font(.footnote).foregroundStyle(.tertiary).padding(.bottom, 4)
            }
        }
    }
}
