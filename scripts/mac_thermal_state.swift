// WP-THERMAL-02: единственный источник теплового состояния Mary Studio.
//
// ProcessInfo.thermalState — системная оценка macOS (public API, без
// приватных интерфейсов и без root). Один запуск процесса = одно измерение,
// поэтому показания обновляются, пока воркер опрашивает helper.
//
// Сборка: swiftc -O -o ~/.mary-studio/bin/mary-thermal-state scripts/mac_thermal_state.swift
// Вывод: одна JSON-строка {"state": "nominal|fair|serious|critical|unknown",
//                          "source": "process_info"}

import Foundation

let state = ProcessInfo.processInfo.thermalState
let name: String
switch state {
case .nominal:
    name = "nominal"
case .fair:
    name = "fair"
case .serious:
    name = "serious"
case .critical:
    name = "critical"
default:
    name = "unknown"
}

let payload: [String: String] = ["state": name, "source": "process_info"]
if let data = try? JSONSerialization.data(withJSONObject: payload, options: []),
   let text = String(data: data, encoding: .utf8) {
    print(text)
} else {
    print("{\"state\":\"unknown\",\"source\":\"process_info\"}")
}
