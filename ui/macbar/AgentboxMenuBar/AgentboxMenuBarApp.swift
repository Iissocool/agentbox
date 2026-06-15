// AgentboxNotch — Window-level drag-drop (like NotchDrop)
import SwiftUI
import Combine

struct WorkspaceItem: Codable, Identifiable {
    var id: String; var name: String; var folder_path: String; var agents: [String]; var pipeline: String; var status: String; var created_at: String
}
struct WorkspaceListResponse: Codable {
    var workspaces: [WorkspaceItem]; var available_agents: [AgentOption]; var pipeline_templates: [String: PipelineTemplate]
}
struct AgentOption: Codable, Identifiable { var id: String; var name: String }
struct PipelineTemplate: Codable { var name: String; var desc: String; var steps: Int }

class StatusMonitor: ObservableObject {
    @Published var currentStatus = SysStatus()
    @Published var workspaces: [WorkspaceItem] = []
    @Published var availableAgents: [AgentOption] = []
    @Published var pipelineTemplates: [String: PipelineTemplate] = [:]
    @Published var isDragOver = false
    private var timer: Timer?
    private let baseURL = "http://localhost:18733"
    struct SysStatus: Codable {
        var status: String = "idle"; var active_agents: [String] = []; var pipeline: String = ""; var progress: Double = 0.0; var alerts: [AlertItem] = []
        struct AlertItem: Codable, Identifiable { var level: String; var message: String; var id: String { message } }
    }
    func startMonitoring() {
        fetchStatus(); fetchWorkspaces()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in self?.fetchStatus(); self?.fetchWorkspaces() }
    }
    private func fetchStatus() {
        guard let url = URL(string: "\(baseURL)/status") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let data = data, let s = try? JSONDecoder().decode(SysStatus.self, from: data) else { return }
            DispatchQueue.main.async { self?.currentStatus = s }
        }.resume()
    }
    func fetchWorkspaces() {
        guard let url = URL(string: "\(baseURL)/workspaces") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let data = data, let r = try? JSONDecoder().decode(WorkspaceListResponse.self, from: data) else { return }
            DispatchQueue.main.async { self?.workspaces = r.workspaces; self?.availableAgents = r.available_agents; self?.pipelineTemplates = r.pipeline_templates }
        }.resume()
    }
    func createWorkspace(folderPath: String) {
        guard let url = URL(string: "\(baseURL)/workspaces") else { return }
        var req = URLRequest(url: url); req.httpMethod = "POST"; req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["folder_path": folderPath, "agents": ["coder"], "pipeline": "single-agent"])
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in DispatchQueue.main.async { self?.fetchWorkspaces() } }.resume()
    }
    func deleteWorkspace(id: String) {
        guard let url = URL(string: "\(baseURL)/workspaces/\(id)") else { return }
        var req = URLRequest(url: url); req.httpMethod = "DELETE"
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in DispatchQueue.main.async { self?.fetchWorkspaces() } }.resume()
    }
    func deleteAllWorkspaces() { for ws in workspaces { deleteWorkspace(id: ws.id) } }
}

// MARK: - Drag-Receiving Content View (window-level)

class NotchContentView: NSHostingView<NotchFloatingView> {
    var monitor: StatusMonitor

    init(monitor: StatusMonitor) {
        self.monitor = monitor
        super.init(rootView: NotchFloatingView(monitor: monitor))
        registerForDraggedTypes([.fileURL, NSPasteboard.PasteboardType("public.file-url")])
    }
    required init?(coder: NSCoder) { fatalError() }
    required init(rootView: NotchFloatingView) { self.monitor = rootView.monitor; super.init(rootView: rootView); registerForDraggedTypes([.fileURL, NSPasteboard.PasteboardType("public.file-url")]) }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        if hasFolder(sender) { DispatchQueue.main.async { self.monitor.isDragOver = true }; return .copy }
        return []
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation { return hasFolder(sender) ? .copy : [] }
    override func draggingExited(_ sender: NSDraggingInfo?) { DispatchQueue.main.async { self.monitor.isDragOver = false } }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        DispatchQueue.main.async { self.monitor.isDragOver = false }
        guard let path = extractFolder(sender) else { return false }
        DispatchQueue.main.async { self.monitor.createWorkspace(folderPath: path) }
        return true
    }
    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool { return true }

    private func hasFolder(_ sender: NSDraggingInfo) -> Bool {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] else { return false }
        return urls.contains { var d: ObjCBool = false; return FileManager.default.fileExists(atPath: $0.path, isDirectory: &d) && d.boolValue }
    }
    private func extractFolder(_ sender: NSDraggingInfo) -> String? {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] else { return nil }
        for u in urls { var d: ObjCBool = false; if FileManager.default.fileExists(atPath: u.path, isDirectory: &d), d.boolValue { return u.path } }
        return nil
    }
}

// MARK: - NotchManager

class NotchManager {
    static let shared = NotchManager()
    var floatingWindow: NSPanel?
    let monitor = StatusMonitor()
    func createFloatingWindow() {
        guard let screen = NSScreen.main else { return }
        let rect = NSRect(x: (screen.frame.width - 320) / 2, y: screen.frame.height - 500, width: 320, height: 500)
        let win = NSPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        win.isOpaque = false; win.backgroundColor = .clear; win.hasShadow = false; win.level = .screenSaver
        win.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        win.ignoresMouseEvents = false; win.acceptsMouseMovedEvents = true
        // Use custom NSHostingView that handles drag at window level
        let contentView = NotchContentView(monitor: monitor)
        win.contentView = contentView; win.orderFrontRegardless(); self.floatingWindow = win
    }
}

// MARK: - Main View

struct NotchFloatingView: View {
    @ObservedObject var monitor: StatusMonitor
    @State private var isExpanded = false
    @State private var selectedTab = 0
    var body: some View {
        VStack(spacing: 0) {
            // Notch bar
            HStack(spacing: 8) {
                Circle().fill(statusColor).frame(width: 8, height: 8).shadow(color: statusColor.opacity(0.8), radius: 4)
                if monitor.isDragOver {
                    Text("DROP FOLDER").font(.system(size: 10, weight: .bold, design: .monospaced)).foregroundColor(.green).tracking(2)
                } else if monitor.currentStatus.active_agents.isEmpty {
                    Text("AGENTBOX").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundColor(.white.opacity(0.6)).tracking(1.5)
                } else {
                    Text(monitor.currentStatus.active_agents.joined(separator: " \u{00b7} ")).font(.system(size: 10, weight: .semibold, design: .monospaced)).foregroundColor(.white.opacity(0.95)).lineLimit(1)
                }
                if monitor.currentStatus.progress > 0 && !monitor.isDragOver {
                    Text("\(Int(monitor.currentStatus.progress * 100))%").font(.system(size: 9, weight: .bold, design: .monospaced)).foregroundColor(.white.opacity(0.8))
                }
                Spacer(minLength: 0)
                if monitor.isDragOver {
                    Image(systemName: "arrow.down.doc.fill").font(.system(size: 10)).foregroundColor(.green)
                } else {
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down").font(.system(size: 8, weight: .bold)).foregroundColor(.white.opacity(0.4))
                }
            }
            .padding(.horizontal, 16)
            .frame(width: monitor.isDragOver ? 260 : 200, height: monitor.isDragOver ? 44 : 32)
            .background(
                RoundedRectangle(cornerRadius: monitor.isDragOver ? 22 : 16)
                    .fill(monitor.isDragOver ? Color.green.opacity(0.3) : Color.black.opacity(0.85))
                    .overlay(RoundedRectangle(cornerRadius: monitor.isDragOver ? 22 : 16).stroke(monitor.isDragOver ? Color.green : Color.clear, lineWidth: 2))
            )
            .animation(.spring(response: 0.2, dampingFraction: 0.7), value: monitor.isDragOver)
            .contentShape(Rectangle())
            .onTapGesture { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded.toggle() } }
            .onHover { if $0 && !isExpanded && !monitor.isDragOver { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded = true } } }

            if isExpanded {
                VStack(spacing: 0) {
                    HStack(spacing: 0) {
                        TabBtn(title: "Status", sel: selectedTab == 0) { selectedTab = 0 }
                        TabBtn(title: "Workspaces (\(monitor.workspaces.count))", sel: selectedTab == 1) { selectedTab = 1 }
                    }.padding(.top, 8)
                    if selectedTab == 0 { StatusPanel(monitor: monitor) }
                    else { WsPanel(monitor: monitor) }
                }
                .frame(width: 320, height: 400)
                .background(UnevenRoundedRectangle(bottomLeadingRadius: 16, bottomTrailingRadius: 16).fill(Color.black.opacity(0.8)).shadow(color: .black.opacity(0.5), radius: 16, y: 8))
                .transition(.asymmetric(insertion: .move(edge: .top).combined(with: .opacity), removal: .move(edge: .top).combined(with: .opacity)))
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(MouseExitView { if isExpanded && !monitor.isDragOver { withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded = false } } })
        .onChange(of: monitor.isDragOver) { _, newValue in
            if newValue && !isExpanded { withAnimation(.spring(response: 0.25, dampingFraction: 0.8)) { isExpanded = true } }
        }
    }
    private var statusColor: Color { monitor.isDragOver ? .green : (monitor.currentStatus.status == "running" ? .yellow : (monitor.currentStatus.status == "degraded" ? .red : .green)) }
}

struct TabBtn: View {
    var title: String; var sel: Bool; var action: () -> Void
    var body: some View { Button(action: action) { Text(title).font(.system(size: 11, weight: sel ? .bold : .regular)).foregroundColor(sel ? .white : .white.opacity(0.4)).padding(.horizontal, 12).padding(.vertical, 6).background(sel ? Color.white.opacity(0.1) : Color.clear).cornerRadius(6) }.buttonStyle(.plain) }
}

struct StatusPanel: View {
    @ObservedObject var monitor: StatusMonitor
    var body: some View { ScrollView { VStack(alignment: .leading, spacing: 8) {
        if monitor.currentStatus.active_agents.isEmpty { HStack { Image(systemName: "moon.zzz.fill").font(.caption).foregroundColor(.white.opacity(0.4)); Text("Idle").font(.system(size: 11)).foregroundColor(.white.opacity(0.5)) } }
        else { ForEach(monitor.currentStatus.active_agents, id: \.self) { a in HStack(spacing: 6) { Circle().fill(.green).frame(width: 6, height: 6); Text(a).font(.system(size: 12, weight: .medium, design: .monospaced)) } } }
        if !monitor.currentStatus.pipeline.isEmpty { Divider().opacity(0.3); Text("Pipeline: \(monitor.currentStatus.pipeline)").font(.system(size: 12)); ProgressView(value: monitor.currentStatus.progress).progressViewStyle(.linear).tint(.green) }
        Spacer(); Divider().opacity(0.3)
        Button(action: { NSApp.terminate(nil) }) { HStack { Image(systemName: "power").font(.caption).foregroundColor(.red); Text("Quit Agentbox").font(.system(size: 11)).foregroundColor(.red) } }.buttonStyle(.plain)
    }.padding(16) } }
}

struct WsPanel: View {
    @ObservedObject var monitor: StatusMonitor
    var body: some View { ScrollView { VStack(alignment: .leading, spacing: 10) {
        VStack(spacing: 6) { Image(systemName: "folder.badge.plus").font(.system(size: 24)).foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.3)); Text(monitor.isDragOver ? "Release to create workspace" : "Drag folder to notch").font(.system(size: 11, weight: .medium)).foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.4)) }
        .frame(maxWidth: .infinity).padding(.vertical, 20).background(RoundedRectangle(cornerRadius: 10).stroke(monitor.isDragOver ? Color.green : Color.white.opacity(0.1), style: StrokeStyle(lineWidth: 2, dash: [6]))).padding(.horizontal, 16)
        if monitor.workspaces.isEmpty { Text("No workspaces yet").font(.system(size: 11)).foregroundColor(.white.opacity(0.3)).frame(maxWidth: .infinity).padding(.top, 8) }
        else {
            ForEach(monitor.workspaces) { ws in WsRow(ws: ws, monitor: monitor) }.padding(.horizontal, 16)
            Button(action: { monitor.deleteAllWorkspaces() }) { HStack { Image(systemName: "xmark.bin").font(.caption).foregroundColor(.red.opacity(0.7)); Text("Close All Workspaces").font(.system(size: 10)).foregroundColor(.red.opacity(0.7)) }.frame(maxWidth: .infinity).padding(.vertical, 6).background(RoundedRectangle(cornerRadius: 6).fill(Color.red.opacity(0.1))) }.buttonStyle(.plain).padding(.horizontal, 16)
        }
        Spacer(); Divider().opacity(0.3)
        Button(action: { NSApp.terminate(nil) }) { HStack { Image(systemName: "power").font(.caption).foregroundColor(.red); Text("Quit Agentbox").font(.system(size: 11)).foregroundColor(.red) } }.buttonStyle(.plain).padding(.horizontal, 16)
    }.padding(.top, 8) } }
}

struct WsRow: View {
    var ws: WorkspaceItem; @ObservedObject var monitor: StatusMonitor
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack { Image(systemName: "folder.fill").font(.caption).foregroundColor(.blue); Text(ws.name).font(.system(size: 13, weight: .semibold)); Spacer()
                Text(ws.status.uppercased()).font(.system(size: 9, design: .monospaced)).foregroundColor(ws.status == "running" ? .yellow : .white.opacity(0.3))
                Button(action: { monitor.deleteWorkspace(id: ws.id) }) { Image(systemName: "xmark.circle.fill").font(.system(size: 12)).foregroundColor(.red.opacity(0.6)) }.buttonStyle(.plain)
            }
            Text(ws.folder_path).font(.system(size: 9, design: .monospaced)).foregroundColor(.white.opacity(0.25)).lineLimit(1)
            HStack(spacing: 4) {
                ForEach(ws.agents, id: \.self) { a in Text(a).font(.system(size: 9, weight: .medium, design: .monospaced)).padding(.horizontal, 6).padding(.vertical, 2).background(Capsule().fill(Color.white.opacity(0.1))).foregroundColor(.white.opacity(0.7)) }
                Spacer()
                Text(ws.pipeline).font(.system(size: 8, design: .monospaced)).padding(.horizontal, 6).padding(.vertical, 2).background(Capsule().fill(Color.blue.opacity(0.3))).foregroundColor(.blue.opacity(0.8))
            }
        }.padding(10).background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.05)))
    }
}

class MouseLeaveView: NSView {
    var onMouseLeave: (() -> Void)?
    override func mouseExited(with event: NSEvent) { onMouseLeave?() }
    override func updateTrackingAreas() { super.updateTrackingAreas(); trackingAreas.forEach { removeTrackingArea($0) }; addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self, userInfo: nil)) }
}
struct MouseExitView: NSViewRepresentable {
    var onMouseLeave: () -> Void
    func makeNSView(context: Context) -> MouseLeaveView { let v = MouseLeaveView(); v.onMouseLeave = onMouseLeave; return v }
    func updateNSView(_ nsView: MouseLeaveView, context: Context) { nsView.onMouseLeave = onMouseLeave }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var notchManager = NotchManager.shared
    func applicationDidFinishLaunching(_ n: Notification) { NSApp.setActivationPolicy(.accessory); notchManager.createFloatingWindow(); notchManager.monitor.startMonitoring() }
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }
}
@main struct AgentboxNotchApp: App { @NSApplicationDelegateAdaptor(AppDelegate.self) var ad; var body: some Scene { Settings {} } }
