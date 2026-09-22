import AppKit
import SwiftUI

struct PreparedDraft: Decodable {
    let text: String
    let before, after, difference: Int
    let percent: Int?
    let counts: String?
    let changed, redacted: Bool
}

@MainActor final class PreparationModel: ObservableObject {
    static let shared = PreparationModel()
    @Published var input = "" { didSet { invalidate() } }
    @Published var mode = "conservative" { didSet { invalidate() } }
    @Published var budget = 2000 { didSet { invalidate() } }
    @Published var result: PreparedDraft?
    @Published var busy = false
    @Published var message: String?
    @Published var error: String?
    private let bridge = MonitorBridge()
    private var revision = 0
    private let limit = 128 * 1024

    var canPrepare: Bool { !busy && !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && input.utf8.count <= limit }
    private func invalidate() {
        revision += 1
        result = nil
        message = nil
        error = input.utf8.count > limit ? "Select a smaller excerpt. The limit is 128 KiB." : nil
    }
    func paste() {
        guard let text = NSPasteboard.general.string(forType: .string) else {
            error = "The clipboard does not contain text."
            return
        }
        guard text.utf8.count <= limit else {
            error = "Clipboard text exceeds 128 KiB. Paste a smaller excerpt."
            return
        }
        input = text
    }
    func prepare() {
        guard canPrepare else { return }
        let source = input, selectedMode = mode, selectedBudget = budget, version = revision
        busy = true
        result = nil
        message = nil
        error = nil
        Task {
            defer { busy = false }
            do {
                let data = try await bridge.request("prepare", text: source, mode: selectedMode, budget: selectedBudget)
                guard revision == version else { return }
                result = try JSONDecoder().decode(PreparedDraft.self, from: data)
            } catch {
                guard revision == version else { return }
                self.error = "Could not prepare this draft. Your original is intact. Check the local TokenCut installation."
            }
        }
    }
    func copyPreview() {
        guard let result else { return }
        NSPasteboard.general.clearContents()
        if NSPasteboard.general.setString(result.text, forType: .string) {
            message = "Copied. Paste it into your chosen chat when ready."
        } else {
            error = "Could not copy the preview. Select and copy its text manually."
        }
    }
    func clear() { input = "" }
}

private func prepareCountsLabel(_ result: PreparedDraft) -> String {
    if let counts = result.counts, !counts.isEmpty { return counts }
    let delta = result.after - result.before
    let percent: Int
    if result.before == 0 {
        percent = result.after == 0 ? 0 : 100
    } else {
        percent = Int((Double(delta) / Double(result.before) * 100).rounded())
    }
    let sign = delta < 0 ? "−" : (delta > 0 ? "+" : "")
    let deltaText = delta == 0 ? "0" : "\(sign)\(count(abs(delta)))"
    let percentText = delta == 0 ? "0%" : "\(sign)\(abs(percent))%"
    return "\(count(result.before)) → \(count(result.after)) (\(deltaText) · \(percentText))"
}

struct PrepareView: View {
    @ObservedObject var model = PreparationModel.shared
    private let green = Color(red: 0.05, green: 0.57, blue: 0.40)
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "text.bubble.fill").font(.title).foregroundStyle(green)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Less to send. More room to work.").font(.title2.bold())
                    Text("Prepare input for Codex, Claude Desktop or any CLI chat.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Text("ON DEVICE").font(.caption2.bold()).foregroundStyle(green)
            }
            HStack(spacing: 12) {
                Picker("Mode", selection: $model.mode) {
                    Text("Preserve diagnostics").tag("conservative")
                    Text("Desktop · Claude / Codex").tag("desktop")
                    Text("Autonomous optimizer · smart").tag("optimize")
                    Text("Conversation summary · lossy").tag("summary")
                }.frame(maxWidth: 400)
                if model.mode == "summary" || model.mode == "optimize" || model.mode == "desktop" {
                    Picker("Target", selection: $model.budget) {
                        Text("800 tokens").tag(800)
                        Text("2,000 tokens").tag(2000)
                        Text("3,000 tokens").tag(3000)
                    }.frame(width: 195)
                }
                Spacer()
                Button("Paste", action: model.paste).help("Read the clipboard once, only when clicked")
                Button("Clear", action: model.clear).disabled(model.input.isEmpty)
            }
            Text(model.mode == "summary"
                 ? "A heuristic summary can miss goals or decisions. Compare both versions before using it. The target is approximate."
                 : model.mode == "desktop"
                 ? "Claude Desktop / Codex Desktop: folds tracebacks and HMR spam, stabilizes cache prefixes, then applies the token budget."
                 : model.mode == "optimize"
                 ? "Autonomous self-routing optimizer: converts embedded JSON to TOON, slims diffs and logs, aligns system prompts, and enforces token ceilings."
                 : "Folds recognized log noise and exact repeated lines. Keeps diagnostic tails and unfamiliar text; does not rewrite prose.")
                .font(.caption).foregroundStyle(
                    model.mode == "summary" ? Color.orange
                    : (model.mode == "optimize" || model.mode == "desktop") ? green
                    : Color.secondary
                )
                .frame(height: 32, alignment: .topLeading)
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Original").font(.headline)
                        Spacer()
                        if let result = model.result {
                            Text("\(count(result.before)) tokens").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                    }
                    TextEditor(text: $model.input)
                        .font(.system(.body, design: .monospaced))
                        .accessibilityLabel("Original draft")
                        .padding(8).background(Color(nsColor: .textBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.primary.opacity(0.12)))
                }
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Preview").font(.headline)
                        Spacer()
                        if let result = model.result {
                            Text("\(count(result.after)) tokens").font(.caption.monospacedDigit()).foregroundStyle(green)
                        }
                    }
                    ScrollView {
                        Text(model.result?.text ?? "Your preview appears here. Nothing is sent automatically.")
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(model.result == nil ? Color.secondary : Color.primary)
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .topLeading).padding(12)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(green.opacity(0.045), in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(green.opacity(0.2)))
                        .accessibilityLabel("Prepared preview")
                }
            }.frame(minHeight: 230, maxHeight: .infinity)
            HStack {
                if model.busy { ProgressView().controlSize(.small) }
                if let result = model.result {
                    Text(prepareCountsLabel(result))
                        .font(.callout.bold().monospacedDigit()).foregroundStyle(green)
                        .accessibilityLabel("Token counts before and after prepare")
                } else {
                    Text("Local tokenizer estimate · no model calls").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Prepare preview", action: model.prepare)
                    .keyboardShortcut(.return, modifiers: .command).disabled(!model.canPrepare)
                Button("Copy preview", action: model.copyPreview)
                    .buttonStyle(.borderedProminent).tint(green).disabled(model.result == nil)
            }
            if let error = model.error { Text(error).font(.caption).foregroundStyle(.orange) }
            if let message = model.message { Text(message).font(.caption).foregroundStyle(green) }
            if model.result?.redacted == true {
                Text("Recognized credentials were redacted. Review the preview before sharing.").font(.caption).foregroundStyle(.orange)
            }
            Text("Preview counts are not account usage or recorded savings. Nothing reads your chats. The original stays here until cleared; compaction may save a redacted copy in TokenCut’s local recovery cache.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }.padding(24).frame(minWidth: 760, minHeight: 570).background(.regularMaterial)
    }
}

@MainActor enum PrepareWindow {
    static var window: NSWindow?
    static func show() {
        if window == nil {
            let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 920, height: 660),
                                 styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            panel.title = "TokenCut — Prepare for chat"
            panel.isReleasedWhenClosed = false
            panel.contentView = NSHostingView(rootView: PrepareView().environment(\.locale, Locale(identifier: "en_US")))
            panel.center()
            window = panel
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
