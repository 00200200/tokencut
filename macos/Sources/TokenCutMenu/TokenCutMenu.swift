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
struct TaskMemory: Decodable {
    let available: Bool
    let tasks, noteTokens, preparedTokens: Int
    let lastSaved, lastCompact, lastRestore: Double?
    let clients, configuredClients, issues: [String]
}
struct Snapshot: Decodable {
    let generatedAt: Double
    let paused: Bool
    let today, prepared: Totals?
    let days: [Day]
    let breakdown: [String: [Group]]
    let legacy: Legacy
    let otherMethodEvents: Int
    let sources, issues: [String]
    let integrations: [Integration]
    let lastCheck: Check?
    let context: TaskMemory?
}

func compact(_ value: Int) -> String {
    let formatter = NumberFormatter()
    formatter.locale = Locale(identifier: "en_US")
    formatter.maximumFractionDigits = abs(value) >= 1000 ? 1 : 0
    let number = abs(value) >= 1000 ? Double(value) / 1000 : Double(value)
    return (formatter.string(from: NSNumber(value: number)) ?? String(value)) + (abs(value) >= 1000 ? "k" : "")
}
func count(_ value: Int) -> String {
    value.formatted(.number.locale(Locale(identifier: "en_US")))
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

    func request(_ method: String, paused: Bool? = nil, text: String? = nil,
                 mode: String? = nil, budget: Int? = nil) throws -> Data {
        try start()
        sequence += 1
        var object: [String: Any] = ["id": sequence, "method": method]
        if let paused { object["paused"] = paused }
        if let text { object["text"] = text }
        if let mode { object["mode"] = mode }
        if let budget { object["budget"] = budget }
        var data = try JSONSerialization.data(withJSONObject: object)
        data.append(10)
        try input?.write(contentsOf: data)
        while !buffer.contains(10) {
            let chunk = output?.availableData ?? Data()
            guard !chunk.isEmpty else {
                process = nil
                throw NSError(domain: "TokenCut", code: 1, userInfo: [NSLocalizedDescriptionKey: "The monitor stopped. Reconnecting on the next refresh."])
            }
            buffer.append(chunk)
            guard buffer.count < 8 * 1024 * 1024 else {
                process?.terminate()
                throw NSError(domain: "TokenCut", code: 2, userInfo: [NSLocalizedDescriptionKey: "The monitor response is too large."])
            }
        }
        let end = buffer.firstIndex(of: 10)!
        let line = Data(buffer[..<end])
        buffer.removeSubrange(...end)
        let envelope = try JSONSerialization.jsonObject(with: line) as? [String: Any]
        guard let result = envelope?["result"], (envelope?["id"] as? Int) == sequence else {
            throw NSError(domain: "TokenCut", code: 3, userInfo: [NSLocalizedDescriptionKey: "The monitor could not complete the request. Check access to local statistics."])
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
    @Published var quotas: [QuotaProvider] = []
    @Published var usageBusy = false
    private let bridge = MonitorBridge()
    private var timer: Timer?
    private var lastRefresh = Date.distantPast
    private var lastUsageRead = Date.distantPast
    private var usagePolls = 0
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
    func refresh() {
        perform("snapshot")
        if Date().timeIntervalSince(lastUsageRead) >= 30 { refreshUsage() }
    }
    func refreshUsage(force: Bool = false) {
        guard !usageBusy else { return }
        usageBusy = true
        if force { usagePolls = 0 }
        Task {
            defer { usageBusy = false }
            do {
                let data = try await bridge.request(force ? "usage-refresh" : "usage")
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                quotas = try decoder.decode(QuotaEnvelope.self, from: data).providers
                lastUsageRead = Date()
                if quotas.contains(where: { $0.status == "loading" }) && usagePolls < 18 {
                    usagePolls += 1
                    Task { [weak model = self] in
                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                        model?.refreshUsage()
                    }
                } else { usagePolls = 0 }
            } catch {
                quotas = []
                lastUsageRead = Date()
            }
        }
    }
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
                    message = (check.ok ? "Check complete: " : "Check failed: ") + check.detail
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
        panel.nameFieldStringValue = "TokenCut-statistics.json"
        panel.title = "Export local statistics"
        panel.prompt = "Export"
        NSApp.activate(ignoringOtherApps: true)
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url, let self else { return }
            Task { @MainActor in
                do {
                    let data = try await self.bridge.request("export")
                    try data.write(to: url, options: .atomic)
                    self.message = "Statistics saved. The export contains only counters and metadata."
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
    @AppStorage("petHidden") private var petHidden = false
    var visibilityKey = "menu"
    private let green = Color(red: 0.05, green: 0.57, blue: 0.40)
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "leaf.fill").font(.title2).foregroundStyle(green)
                VStack(alignment: .leading, spacing: 2) {
                    Text("TokenCut").font(.title3.bold())
                    Text("Less context. More clarity.").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { PrepareWindow.show() } label: { Image(systemName: "square.and.pencil") }
                    .buttonStyle(.plain).help("Prepare for chat").accessibilityLabel("Prepare for chat")
                if model.busy { ProgressView().controlSize(.small) }
                Circle().fill(model.error != nil ? Color.orange : green).frame(width: 7, height: 7)
                    .accessibilityLabel(model.error == nil ? "Local monitor" : "Monitor unavailable")
            }.padding(20)
            Picker("View", selection: $model.tab) {
                Text("Savings").tag(0)
                Text("Tools").tag(1)
                Text("Limits").tag(2)
                Text("Context").tag(3)
            }.pickerStyle(.segmented).padding(.horizontal, 20).padding(.bottom, 16)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let error = model.error { notice(error, icon: "exclamationmark.triangle", color: .orange) }
                    if let message = model.message { notice(message, icon: "checkmark.circle", color: green) }
                    if let data = model.snapshot {
                        if data.paused { notice("Optimization paused. Tools return full output. Recovery is still available.", icon: "pause.circle", color: .orange) }
                        if model.tab == 0 { savings(data) }
                        else if model.tab == 1 { integrations(data) }
                        else if model.tab == 2 { QuotaDetails(model: model) }
                        else { taskMemory(data.context) }
                    } else if model.error == nil {
                        Card { Text("Loading local measurements…").foregroundStyle(.secondary) }
                    }
                }.padding(.horizontal, 20).padding(.bottom, 16)
            }.frame(height: 480)
            Divider()
            HStack {
                Button(action: model.togglePause) {
                    Label(model.snapshot?.paused == true ? "Resume" : "Pause", systemImage: model.snapshot?.paused == true ? "play" : "pause")
                }.keyboardShortcut("p").disabled(model.busy || model.snapshot == nil)
                Spacer()
                Button(petHidden ? "Show pet" : "Hide pet") {
                    if petHidden { PetWindow.show(model) } else { PetWindow.hide() }
                }
                Button("Export", action: model.export).keyboardShortcut("e").disabled(model.busy || model.snapshot == nil)
                Menu {
                    Button("Open dashboard") { PanelWindow.show(model) }
                    Button("Prepare for chat…") { PrepareWindow.show() }.keyboardShortcut("k")
                    Button("Show pet") { PetWindow.show(model) }
                    Button("Refresh", action: model.refresh).keyboardShortcut("r")
                    Button("Quit TokenCut") { NSApp.terminate(nil) }.keyboardShortcut("q")
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
                Text("TODAY · TOKENCUT").font(.caption.bold()).foregroundStyle(.secondary)
                Spacer()
                Text("o200k_base").font(.caption2.monospaced()).foregroundStyle(.secondary)
            }
            if let total = data.today {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("\(total.net >= 0 ? "↓" : "↑") \(count(abs(total.net)))")
                        .font(.system(size: 38, weight: .semibold, design: .rounded)).foregroundStyle(total.net >= 0 ? green : .orange)
                    Text(total.net >= 0 ? "fewer tokens" : "net overhead").font(.caption).foregroundStyle(.secondary)
                }.minimumScaleFactor(0.65).lineLimit(1)
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Before → after").font(.caption).foregroundStyle(.secondary)
                        Text("\(count(total.before)) → \(count(total.after))").font(.headline.monospacedDigit())
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("Recovery cost").font(.caption).foregroundStyle(.secondary)
                        Text("\(count(total.recovery))").font(.headline.monospacedDigit())
                    }
                }
                Text("\(total.events) measurements · recovery included in the net result")
                    .font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("No measurements yet").font(.title2.weight(.semibold))
                Text("Results appear after using the TokenCut wrapper or MCP tools.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            Text("Estimated tool text. This does not measure subscription usage or model reasoning.")
                .font(.caption).foregroundStyle(.secondary)
        }
        Card {
            Text("Last 7 days").font(.headline)
            if data.days.contains(where: { $0.net != nil }) {
                Chart(data.days) { day in
                    if let net = day.net {
                        BarMark(x: .value("Day", day.short), y: .value("Net reduction", net))
                            .foregroundStyle(net >= 0 ? green.gradient : Color.orange.gradient)
                            .cornerRadius(4)
                            .accessibilityLabel("\(day.date): \(net) net tokens")
                    }
                }.chartXScale(domain: data.days.map(\.short)).frame(height: 105)
            } else {
                Text("No chart data yet").font(.callout).foregroundStyle(.secondary).frame(height: 65)
            }
            Text("Days without measurements have no bar.").font(.caption2).foregroundStyle(.secondary)
        }
        Card {
            Picker("Today's measurements by", selection: $model.grouping) {
                Text("Apps").tag("client")
                Text("Projects").tag("project")
                Text("Tools").tag("operation")
            }.pickerStyle(.segmented)
            let groups = data.breakdown[model.grouping] ?? []
            if groups.isEmpty { Text("No attributed measurements").font(.caption).foregroundStyle(.secondary) }
            ForEach(groups) { group in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.grouping == "project" && group.name.hasPrefix("/") ? URL(fileURLWithPath: group.name).lastPathComponent : group.name)
                            .font(.callout).lineLimit(1).help(group.name)
                        Text("\(count(group.before)) → \(count(group.after)) · \(group.events) measurements")
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
                Label("Claude hook · prepared", systemImage: "clock.arrow.circlepath").font(.headline)
                Text("\(count(prepared.before)) → \(count(prepared.after)) · net \(count(prepared.net))")
                Text("The client does not confirm replacement delivery. These measurements stay outside the main counter.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        if data.legacy.events > 0 {
            Text("History: \(data.legacy.events) unattributed legacy measurements. Estimated reduction: \(count(data.legacy.net ?? 0)). Separate from the current counter.")
                .font(.caption).foregroundStyle(.secondary)
        }
        if data.otherMethodEvents > 0 {
            Text("\(data.otherMethodEvents) measurements using another method; excluded from o200k_base.").font(.caption).foregroundStyle(.secondary)
        }
    }
    @ViewBuilder private func taskMemory(_ memory: TaskMemory?) -> some View {
        Card {
            Text("Task memory").font(.headline)
            if let memory, memory.available {
                Text("\(memory.tasks) saved tasks · \(count(memory.noteTokens)) note tokens")
                    .font(.title3.monospacedDigit())
                Text("Short checkpoints retain goals, constraints, decisions and next steps. Up to 20 revisions per task.")
                    .font(.caption).foregroundStyle(.secondary)
                if let timestamp = memory.lastSaved {
                    Text("Last saved: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.month().day().hour().minute().locale(Locale(identifier: "en_US"))))
                        .font(.caption)
                }
            } else {
                Text("No task-memory data yet").foregroundStyle(.secondary)
            }
        }
        Card {
            Text("Native compaction").font(.headline)
            if let memory {
                Text(memory.configuredClients.isEmpty ? "Hooks not configured" : "Configured: " + memory.configuredClients.joined(separator: ", "))
                    .font(.caption)
                Text(memory.clients.isEmpty ? "No hook execution observed" : "Hook execution observed: " + memory.clients.joined(separator: ", "))
                    .font(.caption).foregroundStyle(.secondary)
                if memory.configuredClients.contains("codex") && !memory.clients.contains("codex") {
                    Text("Codex requires you to review and trust the installed hooks.").font(.caption).foregroundStyle(.secondary)
                }
                if let timestamp = memory.lastCompact {
                    Text("Last observed compaction: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.month().day().hour().minute().locale(Locale(identifier: "en_US"))))
                        .font(.caption)
                } else {
                    Text("No compaction observed").font(.caption).foregroundStyle(.secondary)
                }
                if memory.lastRestore != nil {
                    Text("A saved checkpoint was prepared for restoration.").font(.caption)
                }
                if memory.available {
                    Text("Prepared hook context: \(count(memory.preparedTokens)) tokens · o200k_base")
                        .font(.caption.monospacedDigit())
                }
                ForEach(memory.issues, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
            }
            Text("Your client controls compaction. TokenCut restores notes for the same session after compaction or resume; it does not rewrite chat history.")
                .font(.caption).foregroundStyle(.secondary)
        }
        Card {
            Label("Measurement boundaries", systemImage: "info.circle").font(.headline)
            Text("Prepared context is added text, not savings. Delivery to the model is not acknowledged. Full conversation tokens, cache hits and compaction costs are not connected here.")
                .font(.caption).foregroundStyle(.secondary)
            Text("No extra AI calls. Explicit notes stay local and out of statistics exports. Native compaction may consume usage.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private func integrations(_ data: Snapshot) -> some View {
        ForEach(data.integrations) { item in
            Card {
                HStack {
                    Text(item.name).font(.headline)
                    Spacer()
                    Text(item.installed ? "Installed" : "Unavailable")
                        .font(.caption).foregroundStyle(item.installed ? green : .secondary)
                }
                Text(item.clients.isEmpty ? "Not configured" : "Configured: " + item.clients.joined(separator: ", "))
                    .font(.caption)
                if let timestamp = item.lastEvent {
                    Label("Last observed measurement: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.day().month().hour().minute().locale(Locale(identifier: "en_US"))), systemImage: "checkmark.circle")
                        .font(.caption).foregroundStyle(green)
                } else {
                    Text("No confirmed measurement").font(.caption).foregroundStyle(.secondary)
                }
                Text(item.detail).font(.caption).foregroundStyle(.secondary)
            }
        }
        Button(action: model.check) {
            Label("Check integration", systemImage: "checkmark.shield")
                .frame(maxWidth: .infinity)
        }.buttonStyle(.borderedProminent).tint(green).disabled(model.busy).keyboardShortcut("t")
        if let check = data.lastCheck {
            Text((check.ok ? "Local MCP check: OK. " : "Local MCP check: failed. ") + check.detail)
                .font(.caption).foregroundStyle(.secondary)
        }
        ForEach(data.issues, id: \.self) { notice($0, icon: "exclamationmark.triangle", color: .orange) }
        DisclosureGroup("Local data sources (\(data.sources.count))") {
            ForEach(data.sources, id: \.self) { Text($0).font(.caption2.monospaced()).textSelection(.enabled) }
        }.font(.caption)
        Text("Monitor: every 5 s with the panel open, 30 s in the background. No AI calls or network listener.")
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
            panel.contentView = NSHostingView(rootView: PanelView(model: model, visibilityKey: "window").environment(\.locale, Locale(identifier: "en_US")))
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
        if UserDefaults.standard.bool(forKey: "petHidden") {
            UserDefaults.standard.set(true, forKey: "showMenuBar")
        }
        if !UserDefaults.standard.bool(forKey: "petHidden") { PetWindow.show(Model.shared) }
        if CommandLine.arguments.contains("--show-panel") { PanelWindow.show(Model.shared) }
        if CommandLine.arguments.contains("--dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        PetWindow.show(Model.shared)
        return true
    }
}

@main struct TokenCutMenu: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = Model.shared
    @AppStorage("showMenuBar") private var showMenuBar = false
    var body: some Scene {
        MenuBarExtra(isInserted: $showMenuBar) {
            PanelView(model: model).environment(\.locale, Locale(identifier: "en_US"))
        } label: {
            Text(model.title).monospacedDigit()
        }.menuBarExtraStyle(.window)
    }
}
