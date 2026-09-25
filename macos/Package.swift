// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "UsageTrimMenu", platforms: [.macOS(.v13)],
    products: [.executable(name: "UsageTrimMenu", targets: ["UsageTrimMenu"])],
    targets: [.executableTarget(name: "UsageTrimMenu", resources: [.copy("Resources/pet-3d.png")])]
)
