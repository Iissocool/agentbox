// AgentboxNotch — macOS 刘海 AI 状态指示器
// 类似 NotchDrop，在 MacBook 刘海区域显示状态

import SwiftUI
import Combine

struct SystemStatus: Codable {
    var status: String = "idle"
    var active_agents: [String] = []
    var pipeline: String = ""
    var progress: Double = 0.0
    var system_health: String = "ok"
    var alerts: [AlertItem] = []
    var recent_events: [EventItem] = []
    var timestamp: Double = 0
    struct AlertItem: Codable, Identifiable { var level: String; var message: String; var id: String { message } }
    struct EventItem: Codable, Identifiable { var type: String = ""; var source: String = ""; var data: [String: String] = [:]; var timestamp: Double = 0; var id: String { "\(type)-\(timestamp)" } }
}

class StatusMonitor: ObservableObject {
    @Published var currentStatus = SystemStatus()
    private var timer: Timer?
    private let baseURL = "http://localhost:18733"
    func startMonitoring() {
        fetchStatus()
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in self?.fetchStatus() }
    }
    private func fetchStatus() {
        guard let url = URL(string: "\(baseURL)/status") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let data = data, error == nil else { return }
            if let s = try? JSONDecoder().decode(SystemStatus.self, from: data) { DispatchQueue.main.async { self?.currentStatus = s } }
        }.resume()
    }
}

class NotchManager {
    static let shared = NotchManager()
    var notchWindow: NSPanel?
    var popoverWindow: NSPanel?
    let monitor = StatusMonitor()

    func createNotchWindow() {
        guard let screen = NSScreen.main else { return }
        let w: CGFloat = 200, h: CGFloat = 32
        let rect = NSRect(x: (screen.frame.width - w) / 2, y: screen.frame.height - h, width: w, height: h)
        let win = NSPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        win.isOpaque = false
        win.backgroundColor = .clear
        win.hasShadow = false
        win.level = .statusBar + 1
        win.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        win.ignoresMouseEvents = false
        let hosting = NSHostingView(rootView: NotchIndicatorView(monitor: monitor).onTapGesture { self.togglePopover() })
        win.contentView = hosting
        win.orderFrontRegardless()
        self.notchWindow = win
    }

    func togglePopover() { popoverWindow == nil ? showPopover() : closePopover() }

    func showPopover() {
        guard popoverWindow == nil, let screen = NSScreen.main else { return }
        let pw: CGFloat = 300, ph: CGFloat = 380, nh: CGFloat = 32
        let rect = NSRect(x: (screen.frame.width - pw) / 2, y: screen.frame.height - nh - ph, width: pw, height: ph)
        let win = NSPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        win.isOpaque = false
        win.backgroundColor = .clear
        win.hasShadow = true
        win.level = .statusBar
        win.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let hosting = NSHostingView(rootView: NotchPopoverView(monitor: monitor))
        win.contentView = hosting
        win.orderFrontRegardless()
        self.popoverWindow = win
    }

    func closePopover() { popoverWindow?.close(); popoverWindow = nil }
}

struct NotchIndicatorView: View {
    @ObservedObject var monitor: StatusMonitor
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(statusColor).frame(width: 8, height: 8)
                .shadow(color: statusColor.opacity(0.6), radius: 4)
            if !monitor.currentStatus.active_agents.isEmpty {
                Text(monitor.currentStatus.active_agents.joined(separator: ", "))
                    .font(.system(size: 9, weight: .medium, design: .monospaced))
                    .foregroundColor(.white.opacity(0.9)).lineLimit(1)
            }
            if monitor.currentStatus.progress > 0 {
                Text("\(Int(monitor.currentStatus.progress * 100))%")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundColor(.white.opacity(0.8))
            }
        }
        .frame(width: 200, height: 32).contentShape(Rectangle())
    }
    private var statusColor: Color {
        switch monitor.currentStatus.status { case "running": return .yellow; case "degraded": return .red; default: return .green.opacity(0.8) }
    }
}

struct NotchPopoverView: View {
    @ObservedObject var monitor: StatusMonitor
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Circle().fill(statusColor).frame(width: 10, height: 10)
                Text("Agentbox").font(.system(.headline, design: .rounded))
                Spacer()
                Text(monitor.currentStatus.status.uppercased())
                    .font(.system(.caption2, design: .monospaced)).foregroundColor(.secondary)
            }
            Divider()
            if monitor.currentStatus.active_agents.isEmpty {
                HStack {
                    Image(systemName: "moon.fill").font(.caption).foregroundColor(.secondary)
                    Text("No active agents").font(.caption).foregroundColor(.secondary)
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Active Agents").font(.caption).foregroundColor(.secondary)
                    ForEach(monitor.currentStatus.active_agents, id: \.self) { a in
                        HStack(spacing: 6) {
                            Image(systemName: "person.fill").font(.caption2).foregroundColor(.green)
                            Text(a).font(.system(.caption, design: .monospaced))
                        }
                    }
                }
            }
            if !monitor.currentStatus.pipeline.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    Text("Pipeline: \(monitor.currentStatus.pipeline)").font(.caption)
                    ProgressView(value: monitor.currentStatus.progress).progressViewStyle(.linear)
                    Text("\(Int(monitor.currentStatus.progress * 100))%").font(.caption2).foregroundColor(.secondary)
                }
            }
            if !monitor.currentStatus.alerts.isEmpty {
                Divider()
                ForEach(monitor.currentStatus.alerts) { a in
                    HStack {
                        Image(systemName: a.level == "error" ? "xmark.circle.fill" : "exclamationmark.triangle.fill")
                            .font(.caption).foregroundColor(a.level == "error" ? .red : .orange)
                        Text(a.message).font(.caption).foregroundColor(a.level == "error" ? .red : .orange)
                    }
                }
            }
            Spacer()
            Divider()
            HStack {
                Text("localhost:18733").font(.caption2).foregroundColor(.secondary)
                Spacer()
                Text("v0.3.0").font(.caption2).foregroundColor(.secondary)
            }
        }
        .padding(16).frame(width: 268, height: 348)
        .background(RoundedRectangle(cornerRadius: 16)
            .fill(.ultraThinMaterial)
            .shadow(color: .black.opacity(0.3), radius: 12, y: 4))
    }
    private var statusColor: Color {
        switch monitor.currentStatus.status { case "running": return .yellow; case "degraded": return .red; default: return .green }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var notchManager = NotchManager.shared
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        notchManager.createNotchWindow()
        notchManager.monitor.startMonitoring()
    }
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }
}

@main
struct AgentboxNotchApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    var body: some Scene { Settings {} }
}