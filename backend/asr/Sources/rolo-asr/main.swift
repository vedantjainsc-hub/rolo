// rolo-asr: long-running speech-to-text helper for Rolo (see docs/VOICE.md).
//
// Protocol (JSON lines):
//   stdout, once models are loaded:  {"ready": true}
//   stdin:  {"id": "<uuid>", "wav": "/abs/path.wav"}
//   stdout: {"id": "<uuid>", "text": "...", "duration_s": 3.2}  or  {"id": "...", "error": "..."}
// `--warmup`: load (downloading if needed) the models, transcribe 1 s of silence, print
// {"ready": true, "warmup": true} and exit 0.
//
// Only protocol lines go to the real stdout. Everything else (library logs, print) is
// redirected to stderr so it can never corrupt the protocol stream.
import FluidAudio
import Foundation

// ---- stdout isolation -------------------------------------------------------------
let protocolFD = dup(STDOUT_FILENO)
dup2(STDERR_FILENO, STDOUT_FILENO)
let protocolOut = FileHandle(fileDescriptor: protocolFD, closeOnDealloc: false)

func emit(_ obj: [String: Any]) {
    guard var data = try? JSONSerialization.data(withJSONObject: obj, options: []) else { return }
    data.append(0x0A)
    protocolOut.write(data)
}

func log(_ msg: String) {
    FileHandle.standardError.write(("rolo-asr: " + msg + "\n").data(using: .utf8)!)
}

// ---- ASR --------------------------------------------------------------------------
let sampleRate = 16_000
let minSamples = sampleRate  // pad short clips to 1 s; the model rejects very short input

func loadManager() async throws -> AsrManager {
    let models = try await AsrModels.downloadAndLoad(version: .v3)
    let manager = AsrManager(config: .default)
    try await manager.loadModels(models)
    return manager
}

func transcribe(_ manager: AsrManager, samples input: [Float]) async throws -> String {
    let rms = input.isEmpty ? 0 : sqrt(input.reduce(0) { $0 + $1 * $1 } / Float(input.count))
    if input.isEmpty || rms < 1e-5 { return "" }  // silence: nothing to say
    var samples = input
    if samples.count < minSamples { samples += [Float](repeating: 0, count: minSamples - samples.count) }
    var state = TdtDecoderState.make(decoderLayers: await manager.decoderLayerCount)
    let result = try await manager.transcribe(samples, decoderState: &state)
    return result.text.trimmingCharacters(in: .whitespacesAndNewlines)
}

func run() async -> Int32 {
    let warmup = CommandLine.arguments.contains("--warmup")
    let manager: AsrManager
    do {
        let t0 = Date()
        manager = try await loadManager()
        log(String(format: "models loaded in %.1fs", Date().timeIntervalSince(t0)))
    } catch {
        emit(["ready": false, "error": "Could not load speech models: \(error.localizedDescription)"])
        return 2
    }

    if warmup {
        do {
            // A tiny non-silent tone so the full pipeline actually runs once.
            let tone = (0..<sampleRate).map { Float(sin(Double($0) * 2 * .pi * 440 / Double(sampleRate)) * 0.01) }
            _ = try await transcribe(manager, samples: tone)
            emit(["ready": true, "warmup": true])
            return 0
        } catch {
            emit(["ready": false, "error": "Warm-up failed: \(error.localizedDescription)"])
            return 3
        }
    }

    emit(["ready": true])
    let converter = AudioConverter()
    while let line = readLine(strippingNewline: true) {
        if line.trimmingCharacters(in: .whitespaces).isEmpty { continue }
        guard let data = line.data(using: .utf8),
              let req = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = req["id"] as? String
        else {
            emit(["id": "", "error": "bad request line"])
            continue
        }
        guard let path = req["wav"] as? String else {
            emit(["id": id, "error": "missing wav path"])
            continue
        }
        do {
            let samples = try converter.resampleAudioFile(path: path)
            let text = try await transcribe(manager, samples: samples)
            emit(["id": id, "text": text, "duration_s": Double(samples.count) / Double(sampleRate)])
        } catch {
            emit(["id": id, "error": "transcription failed: \(error.localizedDescription)"])
        }
    }
    return 0  // stdin closed: parent went away
}

let code = await run()
exit(code)
