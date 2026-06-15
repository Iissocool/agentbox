// AgentboxMenuBar — macOS Menu Bar App
// 使用 SwiftUI MenuBarExtra 原生 API
// 连接 http://localhost:18733/status

import SwiftUI
import Combine

// MARK: - 数据模型

struct SystemStatus: Codable {
    var status: String = "idle"
    var active_agents: [String] = []
    var pipeline: String = ""
    var progress: Double = 0.0
    var system_health: String = "ok"
    var alerts: [AlertItem] = []
    var recent_events: [EventItem] = []
    var timestamp: Double = 0

    struct AlertItem: Codable, Identifiable {
        var level: String
        var message: String
        var id: String { message }
    }

    struct EventItem: Codable, Identifiable {
        var type: String = ""
        var source: String = ""
        var data: [String: String] = [:]
        var timestamp: Double = 0
        var id: String { "\(timestamp)" }
    }
}

// MARK: - 状态监控

class StatusMonitor: ObservableObject {
    @Published var currentStatus = SystemStatus()
    private var timer: Timer?
    private let baseURL = "http://localhost:18733"

    func startMonitoring() {
        fetchStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.fetchStatus()
        }
    }

    func stopMonitoring() {
        timer?.invalidate()
        timer = nil
    }

    private func fetchStatus() {
        guard let url = URL(string: "\(baseURL)/status") else { return }

        URLSession.shared.dataTask(with: url) { [weak self] data, response, error in
            guard let data = data, error == nil else { return }
            if let status = try? JSONDecoder().decode(SystemStatus.self, from: data) {
                DispatchQueue.main.async {
                    self?.currentStatus = status
                }
            }
        }.resume()
    }
}

// MARK: - AppDelegate (防止 macOS 自动终止代理应用)

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Keep alive as menu bar agent
    }
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }
}

// MARK: - App

@main
struct AgentboxMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var monitor = StatusMonitor()

    var body: some Scene {
        MenuBarExtra("Agentbox", systemImage: statusBarIcon) {
            StatusView(monitor: monitor)
        }
    }

    private var statusBarIcon: String {
        switch monitor.currentStatus.status {
        case "running":
            return "circle.fill"
        case "degraded":
            return "exclamationmark.circle.fill"
        default:
            return "circle"
        }
    }
}

// MARK: - 视图

struct StatusView: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // 标题
            HStack {
                Text("Agentbox")
                    .font(.headline)
                Spacer()
                Circle()
                    .fill(statusColor)
                    .frame(width: 10, height: 10)
                Text(monitor.currentStatus.status)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Divider()

            // Active Agents
            if monitor.currentStatus.active_agents.isEmpty {
                HStack {
                    Image(systemName: "moon.fill")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("No active agents")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            } else {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Active Agents")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(monitor.currentStatus.active_agents, id: \.self) { agent in
                        HStack {
                            Image(systemName: "person.fill")
                                .font(.caption2)
                                .foregroundColor(.green)
                            Text(agent)
                                .font(.system(.caption, design: .monospaced))
                        }
                    }
                }
            }

            // Pipeline
            if !monitor.currentStatus.pipeline.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 3) {
                    Text("Pipeline: \(monitor.currentStatus.pipeline)")
                        .font(.caption)
                    ProgressView(value: monitor.currentStatus.progress)
                        .progressViewStyle(.linear)
                    Text("\(Int(monitor.currentStatus.progress * 100))%")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }

            // Alerts
            if !monitor.currentStatus.alerts.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 3) {
                    Text("Alerts")
                        .font(.caption)
                        .foregroundColor(.red)
                    ForEach(monitor.currentStatus.alerts) { alert in
                        Text("⚠ \(alert.message)")
                            .font(.caption2)
                            .foregroundColor(alert.level == "error" ? .red : .orange)
                    }
                }
            }

            // Recent Events
            if !monitor.currentStatus.recent_events.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 2) {
                    Text("Recent Events")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(monitor.currentStatus.recent_events.prefix(5)) { event in
                        Text("• \(event.type)")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }
            }

            Spacer()

            Divider()

            HStack {
                Text("localhost:18733")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Spacer()
                Text("v0.3.0")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .frame(width: 280, height: 360)
        .onAppear {
            monitor.startMonitoring()
        }
    }

    private var statusColor: Color {
        switch monitor.currentStatus.status {
        case "running": return .yellow
        case "degraded": return .red
        default: return .green
        }
    }
}