import SwiftUI

@MainActor
final class RemindersViewModel: ObservableObject {
    @Published var reminders: [Reminder] = []
    @Published var isLoading = false
    @Published var errorText: String?
    @Published var showAddSheet = false

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            reminders = try await ReminderService.list()
            await NotificationScheduler.rescheduleAll(reminders)
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }

    func create(title: String, due: Date) {
        Task {
            do {
                let created = try await ReminderService.create(
                    Reminder(id: nil, title: title, dueAt: due, done: false, repeatRule: "none", createdAt: nil, updatedAt: nil)
                )
                reminders.append(created)
                await NotificationScheduler.rescheduleAll(reminders)
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    func markDone(_ reminder: Reminder) {
        Task {
            do {
                var copy = reminder
                copy.done = true
                _ = try await ReminderService.update(copy)
                if let idx = reminders.firstIndex(where: { $0.id == copy.id }) { reminders[idx].done = true }
                await NotificationScheduler.rescheduleAll(reminders)
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    func delete(_ reminder: Reminder) {
        Task {
            do {
                try await ReminderService.delete(reminder)
                reminders.removeAll { $0.id == reminder.id }
                await NotificationScheduler.rescheduleAll(reminders)
            } catch {
                errorText = error.localizedDescription
            }
        }
    }
}

struct RemindersView: View {
    @StateObject private var model = RemindersViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.reminders.isEmpty {
                    ProgressView()
                } else if let error = model.errorText, model.reminders.isEmpty {
                    ContentUnavailableView {
                        Label("Impossible de charger", systemImage: "exclamationmark.triangle")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Réessayer") { Task { await model.load() } }
                    }
                } else if model.reminders.isEmpty {
                    ContentUnavailableView {
                        Label("Aucun rappel", systemImage: "bell")
                    } description: {
                        Text("Ajoute-en un avec le bouton + pour être notifié.")
                    }
                } else {
                    List {
                        ForEach(model.reminders) { reminder in
                            HStack(spacing: 12) {
                                Button { model.markDone(reminder) } label: {
                                    Image(systemName: reminder.done ? "checkmark.circle.fill" : "circle")
                                        .font(.title3)
                                }
                                .buttonStyle(.plain)
                                .disabled(reminder.done)

                                VStack(alignment: .leading, spacing: 3) {
                                    Text(reminder.title)
                                        .strikethrough(reminder.done)
                                        .foregroundStyle(reminder.done ? .secondary : .primary)
                                    Text(reminder.dueAt.formatted(date: .abbreviated, time: .shortened))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                            }
                            .swipeActions {
                                Button(role: .destructive) { model.delete(reminder) } label: {
                                    Label("Supprimer", systemImage: "trash")
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Rappels")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { model.showAddSheet = true } label: { Image(systemName: "plus") }
                }
            }
            .sheet(isPresented: $model.showAddSheet) {
                AddReminderSheet { title, due in
                    model.create(title: title, due: due)
                }
            }
            .refreshable { await model.load() }
            .task { await model.load() }
        }
    }
}

struct AddReminderSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var due = Date().addingTimeInterval(3600)
    let onCreate: (String, Date) -> Void

    var body: some View {
        NavigationStack {
            Form {
                TextField("Titre du rappel", text: $title)
                DatePicker("Date", selection: $due, in: Date()...)
            }
            .navigationTitle("Nouveau rappel")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Ajouter") {
                        onCreate(title, due)
                        dismiss()
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
