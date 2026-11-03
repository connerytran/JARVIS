// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ducker",
    platforms: [.macOS("14.2")],  // process taps (AudioHardwareCreateProcessTap) need 14.2
    targets: [
        .executableTarget(name: "ducker"),
    ]
)
