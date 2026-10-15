// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "rolo-asr",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.17.7")
    ],
    targets: [
        .executableTarget(
            name: "rolo-asr",
            dependencies: [.product(name: "FluidAudio", package: "FluidAudio")],
            path: "Sources/rolo-asr"
        )
    ]
)
