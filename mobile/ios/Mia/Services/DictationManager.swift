import AVFoundation
import Foundation
import Speech

/// Dictée vocale locale (framework Speech) : le texte reconnu est ensuite
/// envoyé au chat de Mia. iOS n'expose pas la reconnaissance vocale aux
/// pages web, d'où une implémentation native.
@MainActor
final class DictationManager: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var partialText = ""

    var onFinalText: ((String) -> Void)?

    private let recognizer: SFSpeechRecognizer? = SFSpeechRecognizer(locale: Locale(identifier: "fr-FR"))
    private let audioEngine = AVAudioEngine()
    private var recognitionTask: SFSpeechRecognitionTask?

    var isAvailable: Bool { recognizer?.isAvailable ?? false }

    func toggle() {
        isRecording ? stop() : start()
    }

    func start() {
        guard !isRecording, isAvailable,
              SFSpeechRecognizer.authorizationStatus() == .authorized
        else { return }
        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true

            let node = audioEngine.inputNode
            let recordingFormat = node.outputFormat(forBus: 0)
            node.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
                // Le tap vit sur la queue audio ; on append le buffer directement.
                request.append(buffer)
            }

            recognitionTask = recognizer?.recognitionTask(with: request) { [weak self] result, error in
                // Le rappel arrive sur une queue de fond : on bascule sur le
                // MainActor pour mettre à jour l'état publié.
                guard let self else { return }
                Task { @MainActor in
                    self.handleRecognitionResult(result, error: error)
                }
            }

            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true
            partialText = ""
        } catch {
            cleanup()
        }
    }

    /// Traitement (sur le MainActor) d'un résultat de reconnaissance.
    private func handleRecognitionResult(_ result: SFSpeechRecognitionResult?, error: Error?) {
        if let result {
            partialText = result.bestTranscription.formattedString
            if result.isFinal {
                let text = result.bestTranscription.formattedString
                onFinalText?(text)
            }
        }
        if error != nil {
            cleanup()
        }
    }

    func stop() {
        cleanup()
    }

    private func cleanup() {
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        recognitionTask?.cancel()
        recognitionTask = nil
        partialText = ""
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    static func requestAuthorization() async -> Bool {
        let speechStatus = await SFSpeechRecognizer.requestAuthorization()
        guard speechStatus == .authorized else { return false }
        return await AVAudioApplication.requestRecordPermission()
    }
}
