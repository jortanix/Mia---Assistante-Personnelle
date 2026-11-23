import SwiftUI

@MainActor
final class BriefingViewModel: ObservableObject {
    @Published var briefing: Briefing?
    @Published var isLoading = false
    @Published var errorText: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            briefing = try await BriefingService.today()
            errorText = nil
        } catch {
            errorText = error.localizedDescription
        }
    }
}

struct BriefingView: View {
    @StateObject private var model = BriefingViewModel()

    var body: some View {
        NavigationStack {
            List {
                if model.isLoading {
                    ProgressView()
                } else if let briefing = model.briefing {
                    recapSection(briefing)
                    agendaSection(briefing.calendar)
                    mailsSection(briefing.emails)
                    if briefing.partial {
                        Text("Certaines sources étaient indisponibles : ce point est partiel.")
                            .font(.footnote)
                            .foregroundStyle(.orange)
                    }
                } else if let error = model.errorText {
                    Text(error).foregroundStyle(.red)
                    Button("Réessayer") { Task { await model.load() } }
                } else {
                    Text("Aucune donnée.")
                }
            }
            .navigationTitle("Ta journée")
            .refreshable { await model.load() }
            .task { if model.briefing == nil { await model.load() } }
        }
    }

    private func recapSection(_ briefing: Briefing) -> some View {
        Section {
            LabeledContent("Jour", value: briefing.day)
            LabeledContent("Agenda", value: briefing.calendar.status)
            LabeledContent("Mails", value: briefing.emails.status)
            LabeledContent("Événements", value: "\(briefing.calendar.events.count)")
            LabeledContent("Non lus", value: "\(briefing.emails.messages.filter { $0.unread == true }.count)")
        } header: {
            Text("Récapitulatif")
        }
    }

    private func agendaSection(_ source: CalendarSource) -> some View {
        Section {
            if source.events.isEmpty {
                Text(source.status == "ok" ? "Aucun rendez-vous prévu aujourd'hui." : "Indisponible pour le moment.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(source.events) { event in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            if event.allDay {
                                Image(systemName: "calendar")
                                Text("Toute la journée")
                            } else if let start = event.start {
                                Text(start.formatted(date: .omitted, time: .shortened))
                            }
                            Spacer()
                            if let calendar = event.calendar {
                                Text(calendar).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Text(event.summary).bold()
                        if let location = event.location, !location.isEmpty {
                            Label(location, systemImage: "mappin.and.ellipse").font(.caption)
                        }
                    }
                }
            }
        } header: {
            Text("Agenda")
        }
    }

    private func mailsSection(_ source: EmailSource) -> some View {
        Section {
            if source.messages.isEmpty {
                Text(source.status == "ok" ? "Aucun mail dans la fenêtre." : "Indisponible pour le moment.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(source.messages) { mail in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            if mail.unread == true {
                                Circle().fill(.red).frame(width: 8, height: 8)
                            }
                            Text(mail.subject).bold().lineLimit(1)
                            Spacer()
                            if let date = mail.date {
                                Text(date.formatted(date: .abbreviated, time: .shortened))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if let from = mail.from {
                            Text(from).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                        }
                        if let body = mail.body, !body.isEmpty {
                            Text(body).font(.footnote).lineLimit(2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        } header: {
            Text("Mails récents")
        }
    }
}
