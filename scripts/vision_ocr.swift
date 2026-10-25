import Foundation
import Vision
import AppKit

// Local OCR. Precise recognition first; compatible fallback is explicitly reported.
guard CommandLine.arguments.count >= 2 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let qrOnly = CommandLine.arguments.contains("--qr-only")
do {
    let barcode = VNDetectBarcodesRequest()
    barcode.symbologies = [.qr]; barcode.revision = VNDetectBarcodesRequestRevision1; barcode.usesCPUOnly = true
    try VNImageRequestHandler(url: url, options: [:]).perform([barcode])
    var observations: [VNRecognizedTextObservation] = []
    var flags: [String] = []
    if !qrOnly {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate; request.revision = VNRecognizeTextRequestRevision2
        request.recognitionLanguages = ["en-US"]; request.usesLanguageCorrection = false; request.usesCPUOnly = true
        do { try VNImageRequestHandler(url: url, options: [:]).perform([request]) }
        catch {
            request.recognitionLevel = .fast
            try VNImageRequestHandler(url: url, options: [:]).perform([request])
            flags.append("FAST_COMPATIBILITY_FALLBACK")
        }
        observations = request.results ?? []
    }
    let lines: [[String: Any]] = observations.compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": candidate.string, "confidence": Double(candidate.confidence) * 100,
                "bbox": ["left":box.minX,"top":1-box.maxY,"width":box.width,"height":box.height]]
    }
    let result: [String: Any] = ["text": lines.compactMap { $0["text"] as? String }.joined(separator:"\n"),
                               "words":lines,"flags":flags,"qr_payloads":(barcode.results ?? []).compactMap { $0.payloadStringValue }]
    let data = try JSONSerialization.data(withJSONObject: result)
    print(String(data: data, encoding:.utf8)!)
} catch {
    fputs("Local recognition failed.\n", stderr)
    exit(1)
}
