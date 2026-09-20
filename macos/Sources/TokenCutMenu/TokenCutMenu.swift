import AppKit
import Charts
import SwiftUI
import UniformTypeIdentifiers

struct Totals: Decodable {
    let before, after, net, recovery, events: Int
}
struct Day: Decodable, Identifiable {
    let date: String
    let net: Int?
    var id: String { date }
    var short: String { String(date.suffix(2)) + "." + String(date.dropFirst(5).prefix(2)) }
}
struct Group: Decodable, Identifiable {
    let name: String
    let before, after, net, recovery, events: Int
    var id: String { name }
}
struct Integration: Decodable, Identifiable {
    let name: String
    let installed: Bool
    let clients: [String]
    let lastEvent: Double?
    let detail: String
    var id: String { name }
}
struct Check: Decodable {
    let ok: Bool
    let timestamp: Double
    let detail: String
}
struct Legacy: Decodable {
    let events: Int
    let net: Int?
}
struct Snapshot: Decodable {
    let generatedAt: Double
    let paused: Bool
    let today, prepared, rtk: Totals?
    let days: [Day]
    let breakdown: [String: [Group]]
    let legacy: Legacy
    let otherMethodEvents: Int
    let sources, issues: [String]
    let integrations: [Integration]
    let lastCheck: Check?
}

func compact(_ value: Int) -> String {
    let formatter = NumberFormatter()
    formatter.locale = Locale(identifier: "pl_PL")
    formatter.maximumFractionDigits = abs(value) >= 1000 ? 1 : 0
    let number = abs(value) >= 1000 ? Double(value) / 1000 : Double(value)
    return (formatter.string(from: NSNumber(value: number)) ?? String(value)) + (abs(value) >= 1000 ? "k" : "")
}
func count(_ value: Int) -> String {
    value.formatted(.number.locale(Locale(identifier: "pl_PL")))
}

/// One serial pipe connection; no server socket and no work on the UI thread.
actor MonitorBridge {
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?
    private var buffer = Data()
    private var sequence = 0

    private func start() throws {
        if process?.isRunning == true { return }
        try? input?.close()
        try? output?.close()
        buffer.removeAll()
        let task = Process()
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let bundled = Bundle.main.object(forInfoDictionaryKey: "TokenCutExecutable") as? String
        let executable = ProcessInfo.processInfo.environment["TOKENCUT_EXECUTABLE"] ?? bundled ?? "\(home)/.local/bin/tokencut"
        task.executableURL = URL(fileURLWithPath: executable)
        task.arguments = ["monitor", "--stdio"]
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        environment["RTK_TELEMETRY_DISABLED"] = "1"
        task.environment = environment
        task.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        let request = Pipe(), response = Pipe()
        task.standardInput = request
        task.standardOutput = response
        task.standardError = FileHandle.nullDevice
        try task.run()
        process = task
        input = request.fileHandleForWriting
        output = response.fileHandleForReading
    }

    func request(_ method: String, paused: Bool? = nil) throws -> Data {
        try start()
        sequence += 1
        var object: [String: Any] = ["id": sequence, "method": method]
        if let paused { object["paused"] = paused }
        var data = try JSONSerialization.data(withJSONObject: object)
        data.append(10)
        try input?.write(contentsOf: data)
        while !buffer.contains(10) {
            let chunk = output?.availableData ?? Data()
            guard !chunk.isEmpty else {
                process = nil
                throw NSError(domain: "TokenCut", code: 1, userInfo: [NSLocalizedDescriptionKey: "Proces monitora zakończył pracę. Ponawiam połączenie przy odświeżeniu."])
            }
            buffer.append(chunk)
            guard buffer.count < 8 * 1024 * 1024 else {
                process?.terminate()
                throw NSError(domain: "TokenCut", code: 2, userInfo: [NSLocalizedDescriptionKey: "Odpowiedź monitora jest zbyt duża."])
            }
        }
        let end = buffer.firstIndex(of: 10)!
        let line = Data(buffer[..<end])
        buffer.removeSubrange(...end)
        let envelope = try JSONSerialization.jsonObject(with: line) as? [String: Any]
        guard let result = envelope?["result"], (envelope?["id"] as? Int) == sequence else {
            throw NSError(domain: "TokenCut", code: 3, userInfo: [NSLocalizedDescriptionKey: "Monitor nie mógł wykonać operacji. Sprawdź dostęp do lokalnych statystyk."])
        }
        return try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    }
}

@MainActor final class Model: ObservableObject {
    static let shared = Model()
    @Published var snapshot: Snapshot?
    @Published var error: String?
    @Published var message: String?
    @Published var busy = false
    @Published var tab = 0
    @Published var grouping = "client"
    private let bridge = MonitorBridge()
    private var timer: Timer?
    private var lastRefresh = Date.distantPast
    private var visibleSources: Set<String> = []

    var title: String {
        if error != nil { return "TC !" }
        if snapshot?.paused == true { return "TC Ⅱ" }
        guard let net = snapshot?.today?.net else { return "TC —" }
        return "TC \(net >= 0 ? "↓" : "↑")\(compact(abs(net)))"
    }
    init() { schedule(); refresh() }
    func setVisible(_ value: Bool, source: String = "menu") {
        if value { visibleSources.insert(source) } else { visibleSources.remove(source) }
        schedule()
        if value && Date().timeIntervalSince(lastRefresh) >= 5 { refresh() }
    }
    private func schedule() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: visibleSources.isEmpty ? 30 : 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }
    func refresh() { perform("snapshot") }
    func togglePause() { perform("pause", paused: !(snapshot?.paused ?? false)) }
    func check() { perform("check") }
    private func perform(_ method: String, paused: Bool? = nil) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do {
                let data = try await bridge.request(method, paused: paused)
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                if method == "check" {
                    let check = try decoder.decode(Check.self, from: data)
                    message = (check.ok ? "Test zakończony: " : "Test nieudany: ") + check.detail
                    let update = try await bridge.request("snapshot")
                    snapshot = try decoder.decode(Snapshot.self, from: update)
                } else {
                    snapshot = try decoder.decode(Snapshot.self, from: data)
                }
                error = nil
                lastRefresh = Date()
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
    func export() {
        guard !busy else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "TokenCut-statystyki.json"
        panel.title = "Eksportuj lokalne statystyki"
        panel.prompt = "Eksportuj"
        NSApp.activate(ignoringOtherApps: true)
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url, let self else { return }
            Task { @MainActor in
                do {
                    let data = try await self.bridge.request("export")
                    try data.write(to: url, options: .atomic)
                    self.message = "Statystyki zapisane. Eksport zawiera wyłącznie liczniki i metadane."
                } catch { self.error = error.localizedDescription }
            }
        }
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct PanelView: View {
    @ObservedObject var model: Model
    var visibilityKey = "menu"
    private let green = Color(red: 0.05, green: 0.57, blue: 0.40)
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "leaf.fill").font(.title2).foregroundStyle(green)
                VStack(alignment: .leading, spacing: 2) {
                    Text("TokenCut").font(.title3.bold())
                    Text("Mniej kontekstu. Więcej przejrzystości.").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if model.busy { ProgressView().controlSize(.small) }
                Circle().fill(model.error != nil ? Color.orange : green).frame(width: 7, height: 7)
                    .accessibilityLabel(model.error == nil ? "Monitor lokalny" : "Problem z monitorem")
            }.padding(20)
            Picker("Widok", selection: $model.tab) {
                Text("Oszczędności").tag(0)
                Text("Integracje").tag(1)
            }.pickerStyle(.segmented).padding(.horizontal, 20).padding(.bottom, 16)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = model.error { notice(error, icon: "exclamationmark.triangle", color: .orange) }
                    if let message = model.message { notice(message, icon: "checkmark.circle", color: green) }
                    if let data = model.snapshot {
                        if data.paused { notice("Optymalizacja wstrzymana. Narzędzia zwracają pełny wynik. Odzyskiwanie nadal jest dostępne.", icon: "pause.circle", color: .orange) }
                        if model.tab == 0 { savings(data) } else { integrations(data) }
                    } else if model.error == nil {
                        Card { Text("Wczytywanie lokalnych pomiarów…").foregroundStyle(.secondary) }
                    }
                }.padding(.horizontal, 20).padding(.bottom, 16)
            }.frame(height: 480)
            Divider()
            HStack {
                Button(action: model.togglePause) {
                    Label(model.snapshot?.paused == true ? "Wznów" : "Wstrzymaj", systemImage: model.snapshot?.paused == true ? "play" : "pause")
                }.keyboardShortcut("p").disabled(model.busy || model.snapshot == nil)
                Spacer()
                Button("Eksportuj", action: model.export).keyboardShortcut("e").disabled(model.busy || model.snapshot == nil)
                Menu {
                    Button("Otwórz w oknie") { PanelWindow.show(model) }
                    Button("Odśwież", action: model.refresh).keyboardShortcut("r")
                    Button("Zakończ TokenCut") { NSApp.terminate(nil) }.keyboardShortcut("q")
                } label: { Image(systemName: "ellipsis.circle") }.menuStyle(.borderlessButton).frame(width: 20)
            }.padding(16)
        }.frame(width: 440)
            .background(.regularMaterial)
            .onAppear { model.setVisible(true, source: visibilityKey) }
            .onDisappear { model.setVisible(false, source: visibilityKey) }
    }

    private func notice(_ text: String, icon: String, color: Color) -> some View {
        Label(text, systemImage: icon).font(.caption).foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }
    @ViewBuilder private func savings(_ data: Snapshot) -> some View {
        Card {
            HStack {
                Text("DZISIAJ · TOKENCUT").font(.caption.bold()).foregroundStyle(.secondary)
                Spacer()
                Text("o200k_base").font(.caption2.monospaced()).foregroundStyle(.secondary)
            }
            if let total = data.today {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(total.net >= 0 ? "↓" : "↑") \(count(abs(total.net)))")
                        .font(.system(size: 38, weight: .semibold, design: .rounded)).foregroundStyle(total.net >= 0 ? green : .orange)
                    Text(total.net >= 0 ? "mniej tokenów" : "narzutu netto").font(.caption).foregroundStyle(.secondary)
                }.minimumScaleFactor(0.65).lineLimit(1)
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Przed → po").font(.caption).foregroundStyle(.secondary)
                        Text("\(count(total.before)) → \(count(total.after))").font(.headline.monospacedDigit())
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("Koszt odzyskiwania").font(.caption).foregroundStyle(.secondary)
                        Text("\(count(total.recovery))").font(.headline.monospacedDigit())
                    }
                }
                Text("\(total.events) pomiarów · odzyskiwanie uwzględnione w wyniku netto")
                    .font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("Jeszcze bez pomiarów").font(.title2.weight(.semibold))
                Text("Wyniki pojawią się po użyciu wrappera lub MCP TokenCut.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Text("Szacunek tekstu narzędzi. Nie jest miarą wykorzystania abonamentu ani rozumowania modelu.")
                .font(.caption).foregroundStyle(.secondary)
        }
        Card {
            Text("Ostatnie 7 dni").font(.headline)
            if data.days.contains(where: { $0.net != nil }) {
                Chart(data.days) { day in
                    if let net = day.net {
                        BarMark(x: .value("Dzień", day.short), y: .value("Redukcja netto", net))
                            .foregroundStyle(net >= 0 ? green.gradient : Color.orange.gradient)
                            .cornerRadius(4)
                            .accessibilityLabel("\(day.date): \(net) tokenów netto")
                    }
                }.chartXScale(domain: data.days.map(\.short)).frame(height: 105)
            } else {
                Text("Brak danych do wykresu").font(.callout).foregroundStyle(.secondary).frame(height: 65)
            }
            Text("Dni bez pomiarów nie mają słupka.").font(.caption2).foregroundStyle(.secondary)
        }
        Card {
            Picker("Podział dzisiejszych pomiarów", selection: $model.grouping) {
                Text("Aplikacje").tag("client")
                Text("Projekty").tag("project")
                Text("Narzędzia").tag("operation")
            }.pickerStyle(.segmented)
            let groups = data.breakdown[model.grouping] ?? []
            if groups.isEmpty { Text("Brak przypisanych pomiarów").font(.caption).foregroundStyle(.secondary) }
            ForEach(groups) { group in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.grouping == "project" && group.name.hasPrefix("/") ? URL(fileURLWithPath: group.name).lastPathComponent : group.name)
                            .font(.callout).lineLimit(1).help(group.name)
                        Text("\(count(group.before)) → \(count(group.after)) · \(group.events) pomiarów")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text("\(group.net >= 0 ? "↓" : "↑")\(compact(abs(group.net)))")
                        .font(.callout.monospacedDigit()).foregroundStyle(group.net >= 0 ? green : .orange)
                }
            }
        }
        if let prepared = data.prepared {
            Card {
                Label("Hook Claude · przygotowane", systemImage: "clock.arrow.circlepath").font(.headline)
                Text("\(count(prepared.before)) → \(count(prepared.after)) · netto \(count(prepared.net))")
                Text("Klient nie potwierdza przyjęcia podmiany. Te pomiary są poza głównym licznikiem.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        if data.legacy.events > 0 {
            Text("Historia: \(data.legacy.events) dawnych pomiarów bez przypisania. Szacowana redukcja: \(count(data.legacy.net ?? 0)). Osobno od bieżącego licznika.")
                .font(.caption).foregroundStyle(.secondary)
        }
        if data.otherMethodEvents > 0 {
            Text("\(data.otherMethodEvents) pomiarów inną metodą; poza licznikiem o200k_base.").font(.caption).foregroundStyle(.secondary)
        }
    }
    @ViewBuilder private func integrations(_ data: Snapshot) -> some View {
        ForEach(data.integrations) { item in
            Card {
                HStack {
                    Text(item.name).font(.headline)
                    Spacer()
                    Text(item.installed ? "Zainstalowane" : "Niedostępne")
                        .font(.caption).foregroundStyle(item.installed ? green : .secondary)
                }
                Text(item.clients.isEmpty ? "Brak konfiguracji" : "Skonfigurowane: " + item.clients.joined(separator: ", "))
                    .font(.caption)
                if let timestamp = item.lastEvent {
                    Label("Zaobserwowano pomiar: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.day().month().hour().minute().locale(Locale(identifier: "pl_PL"))), systemImage: "checkmark.circle")
                        .font(.caption).foregroundStyle(green)
                } else {
                    Text("Brak potwierdzonego pomiaru").font(.caption).foregroundStyle(.secondary)
                }
                Text(item.detail).font(.caption).foregroundStyle(.secondary)
                if item.name == "RTK", let total = data.rtk {
                    Text("Dzisiaj: \(count(total.before)) → \(count(total.after)) · netto \(count(total.net))")
                        .font(.callout.monospacedDigit())
                    Text("Bajty / 4. Nie sumujemy z TokenCut.").font(.caption2).foregroundStyle(.secondary)
                }
                if item.name == "Serena" {
                    Link("Konfiguracja Sereny ↗", destination: URL(string: "https://oraios.github.io/serena/02-usage/030_clients.html")!).font(.caption)
                }
            }
        }
        Button(action: model.check) {
            Label("Sprawdź integrację", systemImage: "checkmark.shield")
                .frame(maxWidth: .infinity)
        }.buttonStyle(.borderedProminent).tint(green).disabled(model.busy).keyboardShortcut("t")
        if let check = data.lastCheck {
            Text((check.ok ? "Lokalny test MCP: OK. " : "Lokalny test MCP: błąd. ") + check.detail)
                .font(.caption).foregroundStyle(.secondary)
        }
        ForEach(data.issues, id: \.self) { notice($0, icon: "exclamationmark.triangle", color: .orange) }
        DisclosureGroup("Lokalne źródła danych (\(data.sources.count))") {
            ForEach(data.sources, id: \.self) { Text($0).font(.caption2.monospaced()).textSelection(.enabled) }
        }.font(.caption)
        Text("Monitor: co 5 s przy otwartym panelu, co 30 s w tle. Bez wywołań AI i bez serwera sieciowego.")
            .font(.caption).foregroundStyle(.secondary)
    }
}

@MainActor final class PanelDelegate: NSObject, NSWindowDelegate {
    func windowWillClose(_ notification: Notification) {
        Model.shared.setVisible(false, source: "window")
    }
}

@MainActor enum PanelWindow {
    static let delegate = PanelDelegate()
    static var window: NSWindow?
    static func show(_ model: Model) {
        if window == nil {
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 654),
                                 styleMask: [.titled, .closable], backing: .buffered, defer: false)
            panel.title = "TokenCut"
            panel.isReleasedWhenClosed = false
            panel.delegate = delegate
            panel.contentView = NSHostingView(rootView: PanelView(model: model, visibilityKey: "window").environment(\.locale, Locale(identifier: "pl_PL")))
            panel.center()
            window = panel
        }
        model.setVisible(true, source: "window")
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--show-panel") { PanelWindow.show(Model.shared) }
        if CommandLine.arguments.contains("--dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        PanelWindow.show(Model.shared)
        return true
    }
}

@main struct TokenCutMenu: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = Model.shared
    var body: some Scene {
        MenuBarExtra {
            PanelView(model: model).environment(\.locale, Locale(identifier: "pl_PL"))
        } label: {
            Text(model.title).monospacedDigit()
        }.menuBarExtraStyle(.window)
    }
}
