import SwiftUI

@MainActor
final class SettingsViewModel: ObservableObject {
    @Published var baseURL: String = AppConfig.baseURLString
    @Published var miaApiKey: String = AppConfig.miaApiKey ?? ""
    @Published var briefingKey: String = AppConfig.briefingKey ?? ""
    @Published var saved = false

    func save() {
        let trimmedURL = baseURL.trimmingCharacters(in: .whitespaces)
        AppConfig.baseURLString = trimmedURL.isEmpty ? "http://127.0.0.1:8000" : trimmedURL
        AppConfig.miaApiKey = miaApiKey.isEmpty ? nil : miaApiKey
        AppConfig.briefingKey = briefingKey.isEmpty ? nil : briefingKey
        withAnimation { saved = true }
        Task {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            saved = false
        }
    }
}

struct SettingsView: View {
    @StateObject private var model = SettingsViewModel()

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("URL du backend", text: $model.baseURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Text("Ex. : http://100.x.y.z:8000 (IP Tailscale) ou https://mia-pc.tailXXXX.ts.net. Non exposé sur Internet.")
                        .font(.footnote).foregroundStyle(.secondary)
                } header: {
                    Text("Connexion")
                }

                Section {
                    SecureField("MIA_API_KEY", text: $model.miaApiKey)
                    SecureField("BRIEFING_API_KEY", text: $model.briefingKey)
                } header: {
                    Text("Clés API")
                } footer: {
                    Text("Stockées uniquement dans le trousseau de l'appareil. Jamais envoyées ailleurs qu'au backend.")
                }

                Section {
                    Button {
                        model.save()
                    } label: {
                        Label("Enregistrer", systemImage: "checkmark.circle.fill")
                    }
                    .disabled(model.baseURL.trimmingCharacters(in: .whitespaces).isEmpty)
                    if model.saved {
                        Text("Enregistré ✓").foregroundStyle(.green).font(.footnote)
                    }
                }

                Section {
                    Link("Installer Tailscale", destination: URL(string: "https://tailscale.com/download")!)
                    Text("Version \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0")")
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Réglages")
        }
    }
}
