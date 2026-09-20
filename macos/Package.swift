// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "TokenCutMenu", platforms: [.macOS(.v13)],
    products: [.executable(name: "TokenCutMenu", targets: ["TokenCutMenu"])],
    targets: [.executableTarget(name: "TokenCutMenu", resources: [.copy("Resources/pet-3d.png")])]
)
