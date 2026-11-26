import Foundation

/// Interprète une expression de temps brute en français (« dans 1 heure »,
/// « à 18h », « demain à 9h », « ce soir ») envoyée par le backend dans une
/// proposition de rappel, pour pré-remplir le DatePicker de la carte du chat.
/// Zéro IA : règles déterministes uniquement, dans l'esprit de
/// ``backend/assistant/reminder_rules.py`` côté serveur.
enum ReminderWhen {
    /// Retourne la date suggérée, ou `nil` si rien n'est reconnu (dans ce cas
    /// l'app retombe sur « maintenant + 1 heure »).
    static func parse(_ rawHint: String, relativeTo now: Date = Date()) -> Date? {
        let text = rawHint.lowercased()
        let calendar = Calendar.current

        // « dans 1 heure », « dans 30 minutes », « dans 2h »
        if let caps = firstMatch(#"dans\s+(\d+)\s*(minutes?|min|heures?|h)"#, in: text),
           let amount = Int(caps[1]) {
            let unit: Calendar.Component = caps[2].hasPrefix("h") ? .hour : .minute
            return calendar.date(byAdding: unit, value: amount, to: now)
        }

        // Jour cible. L'ordre compte : « après-demain » avant « demain ».
        var dayOffset = 0
        var defaultHour: Int?
        if text.contains("après-demain") || text.contains("apres-demain") {
            dayOffset = 2
            defaultHour = 9
        } else if text.contains("demain") {
            dayOffset = 1
            defaultHour = 9
        } else if text.contains("ce soir") {
            defaultHour = 20
        } else if text.contains("cet après-midi") || text.contains("cet apres-midi") {
            defaultHour = 15
        } else if text.contains("ce matin") {
            defaultHour = 9
        }

        // Heure absolue : « à 18h30 », « à 18h », « 18 h », « à 9h du matin ».
        var hour: Int?
        var minute = 0
        if let caps = firstMatch(#"(\d{1,2})\s*[h:]\s*(\d{2})?"#, in: text),
           let h = Int(caps[1]), h <= 23 {
            hour = h
            if caps.count > 2, let m = Int(caps[2]), m <= 59 { minute = m }
        }

        let base = calendar.date(byAdding: .day, value: dayOffset, to: now) ?? now
        if let hour {
            var candidate = calendar.date(bySettingHour: hour, minute: minute, second: 0, of: base) ?? base
            // « à 18h » demandé à 21h désigne probablement demain.
            if candidate <= now.addingTimeInterval(60) {
                candidate = calendar.date(byAdding: .day, value: 1, to: candidate) ?? candidate
            }
            return candidate
        }
        guard let defaultHour else { return nil }
        return calendar.date(bySettingHour: defaultHour, minute: 0, second: 0, of: base)
    }

    /// Première occurrence du motif ; groupe 0 = tout le match, puis les captures.
    private static func firstMatch(_ pattern: String, in text: String) -> [String]? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return nil
        }
        let nsRange = NSRange(text.startIndex..., in: text)
        guard let result = regex.firstMatch(in: text, range: nsRange) else { return nil }
        return (0..<result.numberOfRanges).map { i in
            let r = result.range(at: i)
            guard r.location != NSNotFound, let range = Range(r, in: text) else { return "" }
            return String(text[range])
        }
    }
}
