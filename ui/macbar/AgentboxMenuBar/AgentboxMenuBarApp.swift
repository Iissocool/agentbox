// AgentboxMenuBar — macOS Menu Bar App
// 连接 http://localhost:18733/status 和 ws://localhost:18733/stream
// 显示实时 Agent 状态

import SwiftUI
import Combine

@main
struct AgentboxMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // 无主窗口，仅菜单栏
        Settings {}
    }
}

// MARK: - AppDelegate (Menu Bar 控制)

class AppDelegate: NSObject, NSApplicationDelegate {
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    var statusMonitor: StatusMonitor!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // 创建菜单栏状态点
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)

        if let button = statusItem.button {
            button.title = "●"
            button.font = NSFont.systemFont(ofSize: 14)
            button.textColor = .green
        }

        // 创建 Popover
        let contentView = StatusView()
        popover = NSPopover()
        popover.contentSize = NSSize(width: 320, height: 400)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: contentView)

        // 点击事件
        statusItem.button?.action = #selector(togglePopover)
        statusItem.button?.target = self

        // 启动状态监控
        statusMonitor = StatusMonitor()
        statusMonitor.startMonitoring { [weak self] status in
            DispatchQueue.main.async {
                self?.updateStatusBar(status)
            }
        }
    }

    @objc func togglePopover() {
        if let button = statusItem.button {
            if popover.isShown {
                popover.performClose(button)
            } else {
                popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            }
        }
    }

    func updateStatusBar(_ status: SystemStatus) {
        guard let button = statusItem.button else { return }

        switch status.status {
        case "running":
            button.textColor = .systemYellow
        case "degraded":
            button.textColor = .systemRed
        default:
            button.textColor = .systemGreen
        }

        if !status.activeAgents.isEmpty {
            button.toolTip = "Active: \(status.activeAgents.joined(separator: ", "))"
        } else {
            button.toolTip = "Agentbox — Idle"
        }
    }
}

// MARK: - 数据模型

struct SystemStatus: Codable {
    var status: String = "idle"
    var active_agents: [String] = []
    var pipeline: String = ""
    var progress: Double = 0.0
    var system_health: String = "ok"
    var alerts: [AlertItem] = []
    var recent_events: [EventItem] = []

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

// MARK: - 状态监控 (HTTP + WebSocket)

class StatusMonitor: ObservableObject {
    @Published var currentStatus = SystemStatus()
    private var cancellables = Set<AnyCancellable>()
    private let baseURL = "http://localhost:18733"

    func startMonitoring(onUpdate: @escaping (SystemStatus) -> Void) {
        // 定时轮询 /status
        Timer.publish(every: 2, on: .main, in: .common)
            .autoconnect()
            .sink { [weak self] _ in
                self?.fetchStatus(onUpdate: onUpdate)
            }
            .store(in: &cancellables)

        // 初始获取
        fetchStatus(onUpdate: onUpdate)
    }

    private func fetchStatus(onUpdate: @escaping (SystemStatus) -> Void) {
        guard let url = URL(string: "\(baseURL)/status") else { return }

        URLSession.shared.dataTaskPublisher(for: url)
            .map(\.data)
            .decode(type: SystemStatus.self, decoder: JSONDecoder())
            .receive(on: DispatchQueue.main)
            .sink { _ in } receiveValue: { [weak self] status in
                self?.currentStatus = status
                onUpdate(status)
            }
            .store(in: &cancellables)
    }
}

// MARK: - SwiftUI 视图

struct StatusView: View {
    @ObservedObject var monitor = StatusMonitor()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // 标题
            HStack {
                Text("Agentbox")
                    .font(.headline)
                Spacer()
                Circle()
                    .fill(statusColor)
                    .frame(width: 10, height: 10)
            }

            Divider()

            // Active Agents
            if !monitor.currentStatus.active_agents.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Active Agents")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(monitor.currentStatus.active_agents, id: \.self) { agent in
                        HStack {
                            Image(systemName: "person.fill")
                                .font(.caption2)
                            Text(agent)
                                .font(.system(.caption, design: .monospaced))
                        }
                    }
                }
            } else {
                Text("No active agents")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            // Pipeline
            if !monitor.currentStatus.pipeline.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
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
                VStack(alignment: .leading, spacing: 4) {
                    Text("Alerts")
                        .font(.caption)
                        .foregroundColor(.red)
                    ForEach(monitor.currentStatus.alerts) { alert in
                        Text(alert.message)
                            .font(.caption2)
                            .foregroundColor(alert.level == "error" ? .red : .orange)
                    }
                }
            }

            Divider()

            // Recent Events
            if !monitor.currentStatus.recent_events.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Recent Events")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    ForEach(monitor.currentStatus.recent_events.prefix(5)) { event in
                        Text("\(event.type) from \(event.source)")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }
            }

            Spacer()

            Text("Port: 18733")
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .padding()
        .frame(width: 300, height: 380)
    }

    private var statusColor: Color {
        switch monitor.currentStatus.status {
        case "running": return .yellow
        case "degraded": return .red
        default: return .green
        }
    }
}