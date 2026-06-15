// AgentboxNotch — NotchDrop 风格刘海浮层
// 黑色圆角浮层覆盖刘海，悬停/点击展开

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

// MARK: - NotchManager: 单窗口刘海浮层

class NotchManager {
    static let shared = NotchManager()
    var floatingWindow: NSPanel?
    let monitor = StatusMonitor()
    @Published var isHovering = false

    let notchW: CGFloat = 200
    let notchH: CGFloat = 32
    let expandedH: CGFloat = 360
    let expandedW: CGFloat = 280

    func createFloatingWindow() {
        guard let screen = NSScreen.main else { return }
        let rect = NSRect(x: (screen.frame.width - expandedW) / 2,
                          y: screen.frame.height - expandedH,
                          width: expandedW, height: expandedH)
        let win = NSPanel(contentRect: rect,
                          styleMask: [.borderless, .nonactivatingPanel],
                          backing: .buffered, defer: false)
        win.isOpaque = false
        win.backgroundColor = .clear
        win.hasShadow = false
        win.level = .screenSaver
        win.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        win.ignoresMouseEvents = false
        win.acceptsMouseMovedEvents = true

        let hosting = NSHostingView(rootView: NotchFloatingView(monitor: monitor, manager: self))
        win.contentView = hosting
        win.orderFrontRegardless()
        self.floatingWindow = win
    }

    func updateWindowSize(expanded: Bool) {
        guard let win = floatingWindow, let screen = NSScreen.main else { return }
        let h = expanded ? expandedH : notchH + 4
        let w = expanded ? expandedW : notchW
        let rect = NSRect(x: (screen.frame.width - w) / 2,
                          y: screen.frame.height - h,
                          width: expandedW, height: expandedH)
        win.setFrame(rect, display: true, animate: true)
    }
}

// MARK: - 刘海浮层主视图

struct NotchFloatingView: View {
    @ObservedObject var monitor: StatusMonitor
    var manager: NotchManager
    @State private var isExpanded = false
    @State private var hoverCount = 0

    var body: some View {
        VStack(spacing: 0) {
            // 刘海条
            HStack(spacing: 8) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
                    .shadow(color: statusColor.opacity(0.8), radius: 4)
                    .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: monitor.currentStatus.status)

                if !monitor.currentStatus.active_agents.isEmpty {
                    Text(monitor.currentStatus.active_agents.joined(separator: " · "))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.95))
                        .lineLimit(1)
                } else {
                    Text("AGENTBOX")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.6))
                        .tracking(1.5)
                }

                if monitor.currentStatus.progress > 0 {
                    Text("\(Int(monitor.currentStatus.progress * 100))%")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundColor(.white.opacity(0.8))
                }

                Spacer(minLength: 0)

                if isExpanded {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(.white.opacity(0.5))
                } else {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(.white.opacity(0.3))
                }
            }
            .padding(.horizontal, 16)
            .frame(width: 200, height: 32)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.black.opacity(0.85))
            )
            .contentShape(Rectangle())
            .onTapGesture { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded.toggle() } }
            .onHover { hovering in
                if hovering { hoverCount += 1 }
                if hoverCount == 1 && !isExpanded {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded = true }
                }
            }

            // 展开面板
            if isExpanded {
                NotchExpandedPanel(monitor: monitor)
                    .transition(.asymmetric(
                        insertion: .move(edge: .top).combined(with: .opacity),
                        removal: .move(edge: .top).combined(with: .opacity)
                    ))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(MouseInterceptorView(onMouseLeave: {
            if isExpanded {
                hoverCount = 0
                withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded = false }
            }
        }))
    }

    private var statusColor: Color {
        switch monitor.currentStatus.status {
        case "running": return .yellow
        case "degraded": return .red
        default: return .green
        }
    }
}

// MARK: - 展开面板内容

struct NotchExpandedPanel: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Header
            HStack {
                Circle().fill(statusColor).frame(width: 8, height: 8)
                Text("Agentbox").font(.system(.subheadline, design: .rounded)).fontWeight(.semibold)
                Spacer()
                Text(monitor.currentStatus.status.uppercased())
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundColor(statusColor.opacity(0.8))
            }

            Divider().opacity(0.3)

            // Agents
            if monitor.currentStatus.active_agents.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "moon.zzz.fill").font(.caption).foregroundColor(.white.opacity(0.4))
                    Text("Idle — no agents running").font(.system(size: 11)).foregroundColor(.white.opacity(0.5))
                }
            } else {
                VStack(alignment: .leading, spacing: 5) {
                    Text("ACTIVE AGENTS").font(.system(size: 9, weight: .bold)).foregroundColor(.white.opacity(0.4)).tracking(1)
                    ForEach(monitor.currentStatus.active_agents, id: \.self) { a in
                        HStack(spacing: 6) {
                            Circle().fill(Color.green).frame(width: 6, height: 6)
                            Text(a).font(.system(size: 12, weight: .medium, design: .monospaced))
                        }
                    }
                }
            }

            // Pipeline
            if !monitor.currentStatus.pipeline.isEmpty {
                Divider().opacity(0.3)
                VStack(alignment: .leading, spacing: 4) {
                    Text("PIPELINE").font(.system(size: 9, weight: .bold)).foregroundColor(.white.opacity(0.4)).tracking(1)
                    Text(monitor.currentStatus.pipeline).font(.system(size: 12, weight: .medium))
                    ProgressView(value: monitor.currentStatus.progress)
                        .progressViewStyle(.linear)
                        .tint(statusColor)
                    Text("\(Int(monitor.currentStatus.progress * 100))%")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(.white.opacity(0.5))
                }
            }

            // Alerts
            if !monitor.currentStatus.alerts.isEmpty {
                Divider().opacity(0.3)
                VStack(alignment: .leading, spacing: 4) {
                    Text("ALERTS").font(.system(size: 9, weight: .bold)).foregroundColor(.white.opacity(0.4)).tracking(1)
                    ForEach(monitor.currentStatus.alerts) { a in
                        HStack(spacing: 6) {
                            Image(systemName: a.level == "error" ? "xmark.circle.fill" : "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundColor(a.level == "error" ? .red : .orange)
                            Text(a.message).font(.system(size: 11))
                                .foregroundColor(a.level == "error" ? .red.opacity(0.9) : .orange.opacity(0.9))
                        }
                    }
                }
            }

            // Events
            if !monitor.currentStatus.recent_events.isEmpty {
                Divider().opacity(0.3)
                VStack(alignment: .leading, spacing: 3) {
                    Text("RECENT").font(.system(size: 9, weight: .bold)).foregroundColor(.white.opacity(0.4)).tracking(1)
                    ForEach(monitor.currentStatus.recent_events.prefix(4)) { e in
                        Text("\u{2022} \(e.type)")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(.white.opacity(0.4))
                    }
                }
            }

            Spacer()

            Divider().opacity(0.3)
            HStack {
                Text(":18733").font(.system(size: 9, design: .monospaced)).foregroundColor(.white.opacity(0.25))
                Spacer()
                Text("v0.3.0").font(.system(size: 9, design: .monospaced)).foregroundColor(.white.opacity(0.25))
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .frame(width: 280, height: 310)
        .background(
            UnevenRoundedRectangle(bottomLeadingRadius: 16, bottomTrailingRadius: 16)
                .fill(Color.black.opacity(0.75))
                .shadow(color: .black.opacity(0.5), radius: 16, y: 8)
        )
    }

    private var statusColor: Color {
        switch monitor.currentStatus.status { case "running": return .yellow; case "degraded": return .red; default: return .green }
    }
}

// MARK: - 鼠标离开检测 (NSView representable)

class MouseLeaveView: NSView {
    var onMouseLeave: (() -> Void)?
    override func mouseExited(with event: NSEvent) { onMouseLeave?() }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach { removeTrackingArea($0) }
        let ta = NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self, userInfo: nil)
        addTrackingArea(ta)
    }
}

struct MouseInterceptorView: NSViewRepresentable {
    var onMouseLeave: () -> Void
    func makeNSView(context: Context) -> MouseLeaveView {
        let v = MouseLeaveView()
        v.onMouseLeave = onMouseLeave
        return v
    }
    func updateNSView(_ nsView: MouseLeaveView, context: Context) {
        nsView.onMouseLeave = onMouseLeave
    }
}

// MARK: - AppDelegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var notchManager = NotchManager.shared
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        notchManager.createFloatingWindow()
        notchManager.monitor.startMonitoring()
    }
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }
}

@main
struct AgentboxNotchApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    var body: some Scene { Settings {} }
}