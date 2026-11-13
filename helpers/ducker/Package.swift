// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ducker",
    platforms: [.macOS("15.0")],  // Atomic (Synchronization module) needs 15; process taps need 14.2
    targets: [
        .executableTarget(name: "ducker"),
    ]
)
