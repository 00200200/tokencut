import AppKit
import SwiftUI

struct QuotaWindow: Decodable, Identifiable {
    let id, label: String
    let usedPercent, remainingPercent: Double
    let windowMinutes, resetsAt: Double?
}
struct QuotaProvider: Decodable, Identifiable {
    let provider, name, source, status, message: String
    let issue: String?
    let updatedAt: Double?
    let windows: [QuotaWindow]
    var id: String { provider }
    var tightest: QuotaWindow? { windows.min { $0.remainingPercent < $1.remainingPercent } }
}
struct QuotaEnvelope: Decodable { let providers: [QuotaProvider] }

private let petGreen = Color(red: 0.12, green: 0.63, blue: 0.47)

struct PetView: View {
    @ObservedObject var model: Model
    @AppStorage("showMenuBar") private var showMenuBar = false
    @Environment(\.colorScheme) private var colorScheme
    private var dark: Bool { colorScheme == .dark }
    private var ink: Color { dark ? Color(red: 0.92, green: 0.97, blue: 0.95) : Color(red: 0.12, green: 0.22, blue: 0.20) }
    private var mutedInk: Color { dark ? Color(red: 0.70, green: 0.79, blue: 0.76) : Color(red: 0.34, green: 0.43, blue: 0.40) }
    private var accent: Color { dark ? Color(red: 0.43, green: 0.88, blue: 0.69) : Color(red: 0.08, green: 0.46, blue: 0.32) }
    var body: some View {
        HStack(spacing: -4) {
            PetFace(paused: model.snapshot?.paused == true)
            VStack(alignment: .leading, spacing: 9) {
                HStack {
                    Button { showLimits() } label: {
                        Text("TokenCut").font(.system(size: 13, weight: .bold, design: .rounded))
                    }.buttonStyle(.plain).help("Open limits and savings")
                    Spacer(minLength: 6)
                    Menu {
                        Button("Limits and reset") { showLimits() }
                        Button("Savings") { model.tab = 0; PanelWindow.show(model) }
                        Button("Refresh limits") { model.refreshUsage(force: true) }
                        Button(model.snapshot?.paused == true ? "Resume optimization" : "Pause optimization", action: model.togglePause)
                        Divider()
                        Toggle("Also show menu bar", isOn: $showMenuBar)
                        Button("Move to corner") { PetWindow.resetPosition() }
                        Button("Hide pet") { PetWindow.hide() }
                        Button("Quit TokenCut") { NSApp.terminate(nil) }
                    } label: { Image(systemName: "ellipsis") }
                    .menuStyle(.borderlessButton).frame(width: 22).help("Pet options").accessibilityLabel("Pet options")
                    Button { PetWindow.hide() } label: {
                        Image(systemName: "xmark").font(.system(size: 9, weight: .semibold))
                            .frame(width: 14, height: 18)
                    }.buttonStyle(.plain).foregroundStyle(mutedInk)
                        .help("Hide pet — monitoring continues in the menu bar").accessibilityLabel("Hide pet")
                }
                ForEach(["codex", "claude"], id: \.self) { provider in
                    let row = model.quotas.first { $0.provider == provider }
                    Button { showLimits() } label: {
                        HStack(spacing: 4) {
                            Circle().fill(provider == "codex" ? petGreen : Color.orange.opacity(0.8)).frame(width: 5, height: 5)
                            Text(provider == "codex" ? "Codex" : "Claude").foregroundStyle(mutedInk)
                            Spacer(minLength: 4)
                            if let quota = row?.tightest, row?.status == "ok" {
                                Text("\(quota.remainingPercent.formatted(.number.precision(.fractionLength(0))))% left")
                                    .foregroundStyle(quota.remainingPercent <= 15 ? .orange : accent).monospacedDigit().bold()
                            } else {
                                Text(row?.status == "loading" ? "…" : row?.issue == "cli_not_signed_in" ? "CLI not linked" : "unavailable").foregroundStyle(mutedInk)
                            }
                        }.font(.system(size: 11)).padding(.vertical, 2)
                    }.buttonStyle(.plain)
                    .help("Remaining allowance in the most constrained window. Click for all windows and read times.")
                }
                Text(savings).font(.system(size: 10)).foregroundStyle(mutedInk).lineLimit(1)
            }.frame(width: 154)
                .padding(13)
                .foregroundStyle(ink)
                .background {
                    RoundedRectangle(cornerRadius: 21).fill(LinearGradient(
                        colors: dark
                            ? [Color(red: 0.17, green: 0.22, blue: 0.21), Color(red: 0.10, green: 0.14, blue: 0.13)]
                            : [Color(red: 0.98, green: 1, blue: 0.99), Color(red: 0.89, green: 0.95, blue: 0.92)],
                        startPoint: .topLeading, endPoint: .bottomTrailing))
                }
                .overlay(RoundedRectangle(cornerRadius: 21).strokeBorder(ink.opacity(0.12)))
                .shadow(color: .black.opacity(0.10), radius: 8, x: 0, y: 4)
        }
        .padding(8)
        .accessibilityElement(children: .contain)
    }
    private var savings: String {
        if model.error != nil { return "Text measurements unavailable" }
        if model.snapshot?.paused == true { return "Optimization paused" }
        guard let value = model.snapshot?.today?.net else { return "Savings: no measurements" }
        return "Text today: \(value >= 0 ? "↓" : "↑")\(compact(abs(value))) tokens"
    }
    private func showLimits() { model.tab = 2; PanelWindow.show(model) }
}

struct QuotaDetails: View {
    @ObservedObject var model: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Remaining account limits").font(.headline)
            Text("Percentages come from each service. TokenCut text savings are separate. The CLI account may differ from the app account.")
                .font(.caption).foregroundStyle(.secondary)
            if model.quotas.isEmpty {
                Text("No current limit readings.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(model.quotas) { provider in
                Card {
                    HStack {
                        Text(provider.name).font(.headline)
                        Spacer()
                        if provider.status == "loading" { ProgressView().controlSize(.small) }
                    }
                    ForEach(provider.windows) { window in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(window.label)
                                Spacer()
                                Text("\(window.remainingPercent.formatted(.number.precision(.fractionLength(0))))% remaining").monospacedDigit().bold()
                            }.font(.callout)
                            ProgressView(value: window.remainingPercent, total: 100)
                                .tint(window.remainingPercent <= 15 ? .orange : petGreen)
                                .accessibilityLabel("\(window.label): remaining \(Int(window.remainingPercent)) percent")
                            if let reset = window.resetsAt {
                                Text("Reset: " + Date(timeIntervalSince1970: reset).formatted(.dateTime.day().month().hour().minute().locale(Locale(identifier: "en_US"))))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    Text(provider.message).font(.caption).foregroundStyle(.secondary)
                    if let timestamp = provider.updatedAt {
                        Text("Updated: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.hour().minute().locale(Locale(identifier: "en_US"))))
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    Text(provider.source).font(.caption2).foregroundStyle(.secondary)
                    if provider.provider == "claude", provider.status == "unavailable" {
                        Link("View Claude account limits ↗", destination: URL(string: "https://claude.ai/settings/usage")!)
                            .font(.caption)
                    }
                }
            }
            Button("Refresh limits") { model.refreshUsage(force: true) }
                .buttonStyle(.borderedProminent).tint(petGreen).disabled(model.usageBusy)
            Text("Service reads every 5 minutes; manual refresh at most every 30 seconds. No model calls. Missing data does not mean a full allowance. ChatGPT chat limits are not available here.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }
}

final class DraggablePetHost: NSHostingView<PetView> {
    override var mouseDownCanMoveWindow: Bool { true }
}

@MainActor enum PetWindow {
    static var panel: NSPanel?
    static let delegate = PetDelegate()
    static func show(_ model: Model) {
        UserDefaults.standard.set(false, forKey: "petHidden")
        if panel == nil {
            let window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 310, height: 170),
                                 styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            window.title = "TokenCut Pet"
            window.level = .floating
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            window.isMovableByWindowBackground = true
            window.hidesOnDeactivate = false
            window.isOpaque = false
            window.backgroundColor = .clear
            window.hasShadow = true
            window.isReleasedWhenClosed = false
            window.contentView = DraggablePetHost(rootView: PetView(model: model))
            panel = window
            if !window.setFrameUsingName("TokenCutPetPosition") { resetPosition() }
            // Reuse the saved origin while upgrading the old 2D pet's dimensions.
            window.setContentSize(NSSize(width: 310, height: 170))
            clampToScreen()
            window.setFrameAutosaveName("TokenCutPetPosition")
            window.delegate = delegate
            NotificationCenter.default.addObserver(delegate, selector: #selector(PetDelegate.screensChanged),
                name: NSApplication.didChangeScreenParametersNotification, object: nil)
        }
        // Pet counters update on the 30-second background timer; no idle animation.
        clampToScreen()
        panel?.orderFrontRegardless()
    }
    static func hide() {
        UserDefaults.standard.set(true, forKey: "showMenuBar")
        UserDefaults.standard.set(true, forKey: "petHidden")
        panel?.orderOut(nil)
    }
    static func resetPosition() {
        guard let panel, let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let area = screen.visibleFrame
        panel.setFrameOrigin(NSPoint(x: area.maxX - panel.frame.width - 20, y: area.minY + 20))
    }
    static func clampToScreen() {
        guard let panel else { return }
        let screen = NSScreen.screens.first { $0.visibleFrame.intersects(panel.frame) } ?? NSScreen.main
        guard let area = screen?.visibleFrame else { return }
        panel.setFrameOrigin(NSPoint(x: min(max(panel.frame.minX, area.minX), area.maxX - panel.frame.width),
                                    y: min(max(panel.frame.minY, area.minY), area.maxY - panel.frame.height)))
    }
}

@MainActor final class PetDelegate: NSObject, NSWindowDelegate {
    func windowDidMove(_ notification: Notification) {
        PetWindow.panel?.saveFrame(usingName: "TokenCutPetPosition")
    }
    @objc func screensChanged() { PetWindow.clampToScreen() }
}
