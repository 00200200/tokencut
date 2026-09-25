import AppKit
import SwiftUI

// Bundled artwork generated with the built-in imagegen tool; no runtime AI calls.
// Prompt: Create a premium 3D-rendered desktop pet sprite for UsageTrim: an original
// charming mint-green robot with a rounded pear-shaped ceramic body, dark glass
// faceplate, two bright expressive eyes, tiny feet and arms, and one emerald leaf
// antenna. Front three-quarter view, polished collectible-toy quality, soft studio
// lighting, subtle realistic reflections, friendly confident expression. One
// character only, full body, centered, fills 85% of a square canvas. Transparent
// background with true alpha, no floor or background shadow, no text, no logo,
// no UI. Strong readable silhouette at 100 pixels. Sophisticated and adorable,
// not a flat icon.
@MainActor enum PetArtwork {
    static let image: NSImage? = {
        // The packaged app contains the PNG directly; SwiftPM's resource bundle
        // supports `swift run` and the standalone development executable.
        let url = Bundle.main.url(forResource: "pet-3d", withExtension: "png")
            ?? Bundle.module.url(forResource: "pet-3d", withExtension: "png")
        return url.flatMap { NSImage(contentsOf: $0) }
    }()
}

private final class PetHover: ObservableObject {
    @Published var active = false
}

struct PetFace: View {
    var paused: Bool
    @StateObject private var hover = PetHover()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Ellipse().fill(.black.opacity(0.12)).frame(width: 68, height: 8)
                .blur(radius: 4).offset(y: 69)
            SwiftUI.Group {
                if let image = PetArtwork.image {
                    Image(nsImage: image).resizable().interpolation(.high).scaledToFit()
                } else {
                    Image(systemName: "leaf.fill").resizable().scaledToFit().foregroundStyle(.mint)
                }
            }
            .frame(width: 154, height: 154)
            .saturation(paused ? 0.25 : 1)
            .offset(y: hover.active && !reduceMotion ? -3 : 0)
            .rotation3DEffect(.degrees(hover.active && !reduceMotion ? -5 : 0), axis: (x: 0, y: 1, z: 0))
            .animation(reduceMotion ? nil : .easeOut(duration: 0.22), value: hover.active)
            if paused {
                Image(systemName: "pause.fill").font(.system(size: 9, weight: .bold))
                    .padding(6).background(.regularMaterial, in: Circle()).offset(x: 31, y: 48)
            }
        }
        .frame(width: 118, height: 154)
        .onHover { hover.active = $0 }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(paused ? "UsageTrim pet. Optimization paused." : "UsageTrim pet. Drag to move.")
        // A single cached bitmap and event-driven hover keep the idle renderer still.
    }
}
