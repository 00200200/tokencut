import AppKit
import SwiftUI

struct QuotaWindow: Decodable, Identifiable {
    let id, label: String
    let usedPercent, remainingPercent: Double
    let windowMinutes, resetsAt: Double?
}
struct QuotaProvider: Decodable, Identifiable {
    let provider, name, source, status, message: String
    let updatedAt: Double?
    let windows: [QuotaWindow]
    var id: String { provider }
    var tightest: QuotaWindow? { windows.min { $0.remainingPercent < $1.remainingPercent } }
}
struct QuotaEnvelope: Decodable { let providers: [QuotaProvider] }

private let petGreen = Color(red: 0.12, green: 0.63, blue: 0.47)

struct PetFace: View {
    var paused: Bool
    var body: some View {
        ZStack {
            Ellipse().fill(petGreen.opacity(0.15)).frame(width: 62, height: 12).offset(y: 35)
            Image(systemName: "leaf.fill").font(.system(size: 24)).foregroundStyle(petGreen).rotationEffect(.degrees(-30)).offset(x: 6, y: -34)
            RoundedRectangle(cornerRadius: 22).fill((paused ? Color.secondary : petGreen).gradient)
                .frame(width: 66, height: 63)
            HStack(spacing: 16) {
                Capsule().frame(width: 6, height: paused ? 3 : 12)
                Capsule().frame(width: 6, height: paused ? 3 : 12)
            }.foregroundStyle(.white).offset(y: -4)
            Capsule().fill(.white.opacity(0.85)).frame(width: 13, height: 3).offset(y: 13)
        }.frame(width: 78, height: 84)
            .accessibilityLabel(paused ? "Pupil TokenCut, optymalizacja wstrzymana" : "Pupil TokenCut. Przeciągnij, aby zmienić położenie.")
    }
}

struct PetView: View {
    @ObservedObject var model: Model
    @AppStorage("showMenuBar") private var showMenuBar = false
    var body: some View {
        HStack(spacing: 8) {
            PetFace(paused: model.snapshot?.paused == true)
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Button { showLimits() } label: {
                        Text("TokenCut").font(.system(size: 13, weight: .bold, design: .rounded))
                    }.buttonStyle(.plain).help("Otwórz limity i oszczędności")
                    Spacer(minLength: 6)
                    Text("zostało").font(.system(size: 9)).foregroundStyle(.secondary)
                    Menu {
                        Button("Limity i reset") { showLimits() }
                        Button("Oszczędności") { model.tab = 0; PanelWindow.show(model) }
                        Button("Odśwież limity") { model.refreshUsage(force: true) }
                        Button(model.snapshot?.paused == true ? "Wznów optymalizację" : "Wstrzymaj optymalizację", action: model.togglePause)
                        Divider()
                        Toggle("Pokaż także pasek menu", isOn: $showMenuBar)
                        Button("Przenieś do rogu") { PetWindow.resetPosition() }
                        Button("Ukryj pupila") { PetWindow.hide() }
                        Button("Zakończ TokenCut") { NSApp.terminate(nil) }
                    } label: { Image(systemName: "ellipsis") }
                    .menuStyle(.borderlessButton).frame(width: 22).help("Opcje pupila").accessibilityLabel("Opcje pupila")
                }
                ForEach(["codex", "claude"], id: \.self) { provider in
                    let row = model.quotas.first { $0.provider == provider }
                    Button { showLimits() } label: {
                        HStack(spacing: 4) {
                            Text(provider == "codex" ? "Codex" : "Claude").foregroundStyle(.secondary)
                            Spacer(minLength: 4)
                            if let quota = row?.tightest, row?.status == "ok" {
                                Text("\(quota.remainingPercent.formatted(.number.precision(.fractionLength(0))))%")
                                    .foregroundStyle(quota.remainingPercent <= 15 ? .orange : petGreen).monospacedDigit().bold()
                            } else {
                                Text(row?.status == "loading" ? "…" : "brak danych").foregroundStyle(.secondary)
                            }
                        }.font(.system(size: 11))
                    }.buttonStyle(.plain)
                    .help("Pozostały limit najbardziej wykorzystanego okna. Kliknij, aby zobaczyć wszystkie okna i czas odczytu.")
                }
                Text(savings).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
            }.frame(width: 152)
        }
        .padding(.horizontal, 12).padding(.vertical, 12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).strokeBorder(.primary.opacity(0.08)))
        .padding(4)
        .accessibilityElement(children: .contain)
    }
    private var savings: String {
        if model.error != nil { return "Pomiar tekstu niedostępny" }
        if model.snapshot?.paused == true { return "Optymalizacja wstrzymana" }
        guard let value = model.snapshot?.today?.net else { return "Oszczędności: brak pomiarów" }
        return "Tekst dziś: \(value >= 0 ? "↓" : "↑")\(compact(abs(value))) tok."
    }
    private func showLimits() { model.tab = 2; PanelWindow.show(model) }
}

struct QuotaDetails: View {
    @ObservedObject var model: Model
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Pozostałe limity kont").font(.headline)
            Text("Procenty pochodzą z usług. Oszczędności tekstu TokenCut są osobnym pomiarem. Konto CLI może różnić się od konta w aplikacji.")
                .font(.caption).foregroundStyle(.secondary)
            if model.quotas.isEmpty {
                Text("Brak aktualnego odczytu limitów.").font(.caption).foregroundStyle(.secondary)
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
                                Text("\(window.remainingPercent.formatted(.number.precision(.fractionLength(0))))% zostało").monospacedDigit().bold()
                            }.font(.callout)
                            ProgressView(value: window.remainingPercent, total: 100)
                                .tint(window.remainingPercent <= 15 ? .orange : petGreen)
                                .accessibilityLabel("\(window.label): pozostało \(Int(window.remainingPercent)) procent")
                            if let reset = window.resetsAt {
                                Text("Reset: " + Date(timeIntervalSince1970: reset).formatted(.dateTime.day().month().hour().minute().locale(Locale(identifier: "pl_PL"))))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    Text(provider.message).font(.caption).foregroundStyle(.secondary)
                    if let timestamp = provider.updatedAt {
                        Text("Odczyt: " + Date(timeIntervalSince1970: timestamp).formatted(.dateTime.hour().minute().locale(Locale(identifier: "pl_PL"))))
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    Text(provider.source).font(.caption2).foregroundStyle(.secondary)
                    if provider.provider == "claude", provider.status == "unavailable" {
                        Text("Sprawdź logowanie w Claude Code CLI. Logowanie w Claude Desktop może być osobne.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Button("Odśwież limity") { model.refreshUsage(force: true) }
                .buttonStyle(.borderedProminent).tint(petGreen).disabled(model.usageBusy)
            Text("Odczyt z usług co 5 minut; ręcznie najwyżej co 30 sekund. Bez zapytań do modeli. Brak danych nie oznacza pełnego limitu. Limity samego czatu ChatGPT nie są tu udostępniane.")
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
            let window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 270, height: 124),
                                 styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            window.title = "Pupil TokenCut"
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
