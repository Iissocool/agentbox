// AgentboxNotch — AppKit drag host + NotchDrop-like glass UI
import SwiftUI
import Combine
import AppKit

// MARK: - Models

struct WorkspaceItem: Codable, Identifiable {
    var id: String
    var name: String
    var folder_path: String
    var agents: [String]
    var pipeline: String
    var status: String
    var created_at: String
}

struct WorkspaceListResponse: Codable {
    var workspaces: [WorkspaceItem]
    var available_agents: [AgentOption]
    var pipeline_templates: [String: PipelineTemplate]
}

struct AgentOption: Codable, Identifiable {
    var id: String
    var name: String
}

struct PipelineTemplate: Codable {
    var name: String
    var desc: String
    var steps: Int
}

// MARK: - State / API client

final class StatusMonitor: ObservableObject {
    @Published var currentStatus = SysStatus()
    @Published var workspaces: [WorkspaceItem] = []
    @Published var availableAgents: [AgentOption] = []
    @Published var pipelineTemplates: [String: PipelineTemplate] = [:]

    // UI state is centralized so AppKit drag callbacks can open/switch the SwiftUI panel.
    @Published var isDragOver = false
    @Published var isExpanded = false
    @Published var selectedTab = 1
    @Published var lastDropMessage = "Drag a folder onto the notch"

    private var timer: Timer?
    private let baseURL = "http://localhost:18733"

    struct SysStatus: Codable {
        var status: String = "idle"
        var active_agents: [String] = []
        var pipeline: String = ""
        var progress: Double = 0.0
        var alerts: [AlertItem] = []

        struct AlertItem: Codable, Identifiable {
            var level: String
            var message: String
            var id: String { message }
        }
    }

    func startMonitoring() {
        fetchStatus()
        fetchWorkspaces()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.fetchStatus()
            self?.fetchWorkspaces()
        }
    }

    private func fetchStatus() {
        guard let url = URL(string: "\(baseURL)/status") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let data, let status = try? JSONDecoder().decode(SysStatus.self, from: data) else { return }
            DispatchQueue.main.async { self?.currentStatus = status }
        }.resume()
    }

    func fetchWorkspaces() {
        guard let url = URL(string: "\(baseURL)/workspaces") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let data, let response = try? JSONDecoder().decode(WorkspaceListResponse.self, from: data) else { return }
            DispatchQueue.main.async {
                self?.workspaces = response.workspaces
                self?.availableAgents = response.available_agents
                self?.pipelineTemplates = response.pipeline_templates
            }
        }.resume()
    }

    func createWorkspace(folderPath: String) {
        lastDropMessage = "Creating workspace: \(URL(fileURLWithPath: folderPath).lastPathComponent)"
        guard let url = URL(string: "\(baseURL)/workspaces") else { return }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: [
            "folder_path": folderPath,
            "agents": ["coder"],
            "pipeline": "single-agent",
        ])

        URLSession.shared.dataTask(with: request) { [weak self] _, _, error in
            DispatchQueue.main.async {
                if let error {
                    self?.lastDropMessage = "Gateway error: \(error.localizedDescription)"
                } else {
                    self?.lastDropMessage = "Workspace created"
                }
                self?.selectedTab = 1
                self?.isExpanded = true
                self?.fetchWorkspaces()
            }
        }.resume()
    }

    func deleteWorkspace(id: String) {
        guard let url = URL(string: "\(baseURL)/workspaces/\(id)") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        URLSession.shared.dataTask(with: request) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.fetchWorkspaces() }
        }.resume()
    }

    func deleteAllWorkspaces() {
        let ids = workspaces.map(\.id)
        for id in ids { deleteWorkspace(id: id) }
    }
}

// MARK: - AppKit drag host

final class NotchDragCoordinator {
    let monitor: StatusMonitor

    init(monitor: StatusMonitor) {
        self.monitor = monitor
    }

    let fileTypes: [NSPasteboard.PasteboardType] = [
        .fileURL,
        .URL,
        NSPasteboard.PasteboardType("public.file-url"),
        NSPasteboard.PasteboardType("NSFilenamesPboardType"),
    ]

    func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        logPasteboard(sender, phase: "entered")
        guard !folderPaths(from: sender).isEmpty else { return [] }
        DispatchQueue.main.async {
            self.monitor.isDragOver = true
            self.monitor.isExpanded = true
            self.monitor.selectedTab = 1
            self.monitor.lastDropMessage = "Release to create workspace"
        }
        return .copy
    }

    func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        return folderPaths(from: sender).isEmpty ? [] : .copy
    }

    func draggingExited(_ sender: NSDraggingInfo?) {
        DispatchQueue.main.async {
            self.monitor.isDragOver = false
            self.monitor.lastDropMessage = "Drag a folder onto the notch"
        }
        logDrag("dragging exited")
    }

    func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        return !folderPaths(from: sender).isEmpty
    }

    func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let paths = folderPaths(from: sender)
        logDrag("perform drop paths=\(paths)")
        DispatchQueue.main.async { self.monitor.isDragOver = false }
        guard let first = paths.first else { return false }
        DispatchQueue.main.async {
            self.monitor.selectedTab = 1
            self.monitor.isExpanded = true
            self.monitor.createWorkspace(folderPath: first)
        }
        return true
    }

    private func folderPaths(from sender: NSDraggingInfo) -> [String] {
        let pasteboard = sender.draggingPasteboard
        var results: [String] = []

        if let files = pasteboard.propertyList(forType: NSPasteboard.PasteboardType("NSFilenamesPboardType")) as? [String] {
            results.append(contentsOf: files)
        }

        if let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] {
            results.append(contentsOf: urls.map(\.path))
        }

        for type in [NSPasteboard.PasteboardType.fileURL, NSPasteboard.PasteboardType("public.file-url"), NSPasteboard.PasteboardType.URL] {
            if let value = pasteboard.string(forType: type) {
                if let url = URL(string: value), url.isFileURL {
                    results.append(url.path)
                } else {
                    results.append(value)
                }
            }
        }

        return Array(Set(results)).filter { path in
            var isDirectory: ObjCBool = false
            return FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) && isDirectory.boolValue
        }
    }

    private func logPasteboard(_ sender: NSDraggingInfo, phase: String) {
        let types = sender.draggingPasteboard.types?.map(\.rawValue) ?? []
        logDrag("\(phase) pasteboard types=\(types)")
    }

    func logDrag(_ message: String) {
        let line = "[\(Date())] \(message)\n"
        if let data = line.data(using: .utf8) {
            let url = URL(fileURLWithPath: "/tmp/agentbox_notch_drag.log")
            if FileManager.default.fileExists(atPath: url.path),
               let handle = try? FileHandle(forWritingTo: url) {
                handle.seekToEndOfFile()
                handle.write(data)
                try? handle.close()
            } else {
                try? data.write(to: url)
            }
        }
    }
}

final class DragAwareHostingView: NSHostingView<NotchFloatingView> {
    private let coordinator: NotchDragCoordinator

    init(rootView: NotchFloatingView, coordinator: NotchDragCoordinator) {
        self.coordinator = coordinator
        super.init(rootView: rootView)
        registerForDraggedTypes(coordinator.fileTypes)
    }

    @available(*, unavailable)
    required init(rootView: NotchFloatingView) {
        fatalError("Use init(rootView:coordinator:)")
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        coordinator.draggingEntered(sender)
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        coordinator.draggingUpdated(sender)
    }

    override func draggingExited(_ sender: NSDraggingInfo?) {
        coordinator.draggingExited(sender)
    }

    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        coordinator.prepareForDragOperation(sender)
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        coordinator.performDragOperation(sender)
    }
}

final class NotchDragHostView: NSView {
    private let coordinator: NotchDragCoordinator
    private let hostingView: DragAwareHostingView

    init(monitor: StatusMonitor) {
        self.coordinator = NotchDragCoordinator(monitor: monitor)
        self.hostingView = DragAwareHostingView(rootView: NotchFloatingView(monitor: monitor), coordinator: coordinator)
        super.init(frame: .zero)

        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor

        registerForDraggedTypes(coordinator.fileTypes)

        hostingView.translatesAutoresizingMaskIntoConstraints = false
        hostingView.wantsLayer = true
        hostingView.layer?.backgroundColor = NSColor.clear.cgColor
        addSubview(hostingView)

        NSLayoutConstraint.activate([
            hostingView.leadingAnchor.constraint(equalTo: leadingAnchor),
            hostingView.trailingAnchor.constraint(equalTo: trailingAnchor),
            hostingView.topAnchor.constraint(equalTo: topAnchor),
            hostingView.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])

        coordinator.logDrag("Drag host initialized on container + hosting view; registered types: \(coordinator.fileTypes.map { $0.rawValue })")
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func hitTest(_ point: NSPoint) -> NSView? {
        // Keep SwiftUI interactive while this container still receives dragging callbacks.
        return super.hitTest(point)
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        coordinator.draggingEntered(sender)
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        coordinator.draggingUpdated(sender)
    }

    override func draggingExited(_ sender: NSDraggingInfo?) {
        coordinator.draggingExited(sender)
    }

    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        coordinator.prepareForDragOperation(sender)
    }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        coordinator.performDragOperation(sender)
    }
}

// MARK: - Window manager

final class NotchManager {
    static let shared = NotchManager()
    var floatingWindow: NSPanel?
    let monitor = StatusMonitor()

    func createFloatingWindow() {
        guard let screen = NSScreen.main else { return }

        let width: CGFloat = 380
        let height: CGFloat = 560
        let visible = screen.visibleFrame
        let rect = NSRect(
            x: visible.midX - width / 2,
            y: visible.maxY - height + 8,
            width: width,
            height: height
        )

        let window = NSPanel(
            contentRect: rect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.level = .screenSaver
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        window.ignoresMouseEvents = false
        window.acceptsMouseMovedEvents = true
        window.isMovableByWindowBackground = false
        window.contentView = NotchDragHostView(monitor: monitor)
        window.orderFrontRegardless()

        floatingWindow = window
    }
}

// MARK: - SwiftUI UI

struct NotchFloatingView: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 0) {
            NotchCapsule(monitor: monitor)

            if monitor.isExpanded {
                NotchPanel(monitor: monitor)
                    .transition(.asymmetric(
                        insertion: .move(edge: .top).combined(with: .opacity).combined(with: .scale(scale: 0.98, anchor: .top)),
                        removal: .move(edge: .top).combined(with: .opacity)
                    ))
            }

            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.top, 2)
        .background(MouseExitView {
            if monitor.isExpanded && !monitor.isDragOver {
                withAnimation(.spring(response: 0.36, dampingFraction: 0.82)) {
                    monitor.isExpanded = false
                }
            }
        })
        .onChange(of: monitor.isDragOver) { _, dragging in
            if dragging {
                withAnimation(.spring(response: 0.26, dampingFraction: 0.78)) {
                    monitor.isExpanded = true
                    monitor.selectedTab = 1
                }
            }
        }
    }
}

struct NotchCapsule: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle().fill(statusColor.opacity(0.22)).frame(width: 18, height: 18)
                Circle().fill(statusColor).frame(width: 8, height: 8)
            }
            .shadow(color: statusColor.opacity(0.7), radius: monitor.isDragOver ? 12 : 5)

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: monitor.isDragOver ? 12 : 10, weight: .bold, design: .rounded))
                    .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.92))
                    .tracking(monitor.isDragOver ? 1.8 : 1.2)

                if monitor.isDragOver {
                    Text("Release to create a workspace")
                        .font(.system(size: 8.5, weight: .medium, design: .rounded))
                        .foregroundColor(.green.opacity(0.82))
                }
            }

            Spacer(minLength: 0)

            Image(systemName: monitor.isDragOver ? "arrow.down.circle.fill" : (monitor.isExpanded ? "chevron.up" : "sparkles"))
                .font(.system(size: monitor.isDragOver ? 17 : 12, weight: .semibold))
                .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.52))
        }
        .padding(.horizontal, monitor.isDragOver ? 18 : 14)
        .frame(width: monitor.isDragOver ? 304 : 218, height: monitor.isDragOver ? 58 : 36)
        .background(capsuleBackground)
        .overlay(
            RoundedRectangle(cornerRadius: monitor.isDragOver ? 29 : 18)
                .stroke(monitor.isDragOver ? Color.green.opacity(0.95) : Color.white.opacity(0.08), lineWidth: monitor.isDragOver ? 2 : 1)
        )
        .shadow(color: monitor.isDragOver ? .green.opacity(0.38) : .black.opacity(0.45), radius: monitor.isDragOver ? 22 : 14, y: monitor.isDragOver ? 8 : 6)
        .contentShape(Rectangle())
        .onTapGesture {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                monitor.isExpanded.toggle()
            }
        }
        .onHover { hovering in
            if hovering && !monitor.isExpanded && !monitor.isDragOver {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                    monitor.isExpanded = true
                }
            }
        }
        .animation(.spring(response: 0.25, dampingFraction: 0.72), value: monitor.isDragOver)
    }

    private var title: String {
        if monitor.isDragOver { return "DROP FOLDER" }
        if !monitor.currentStatus.active_agents.isEmpty {
            return monitor.currentStatus.active_agents.joined(separator: " · ").uppercased()
        }
        return "AGENTBOX"
    }

    private var statusColor: Color {
        if monitor.isDragOver { return .green }
        switch monitor.currentStatus.status {
        case "running": return .yellow
        case "degraded": return .red
        default: return .green
        }
    }

    private var capsuleBackground: some View {
        RoundedRectangle(cornerRadius: monitor.isDragOver ? 29 : 18)
            .fill(
                LinearGradient(
                    colors: monitor.isDragOver
                        ? [Color.green.opacity(0.30), Color.black.opacity(0.88), Color.green.opacity(0.18)]
                        : [Color.black.opacity(0.94), Color(red: 0.04, green: 0.045, blue: 0.055).opacity(0.92)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .overlay(
                RoundedRectangle(cornerRadius: monitor.isDragOver ? 29 : 18)
                    .fill(Color.white.opacity(0.035))
                    .blur(radius: 0.5)
            )
    }
}

struct NotchPanel: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 8) {
                TabButton(title: "Status", icon: "waveform.path.ecg", isSelected: monitor.selectedTab == 0) {
                    monitor.selectedTab = 0
                }
                TabButton(title: "Workspaces", icon: "folder.fill", badge: monitor.workspaces.count, isSelected: monitor.selectedTab == 1) {
                    monitor.selectedTab = 1
                }
            }
            .padding(.top, 12)
            .padding(.horizontal, 14)

            if monitor.selectedTab == 0 {
                StatusPanel(monitor: monitor)
            } else {
                WorkspacePanel(monitor: monitor)
            }
        }
        .frame(width: 356, height: 456)
        .background(panelBackground)
        .overlay(
            UnevenRoundedRectangle(topLeadingRadius: 8, bottomLeadingRadius: 26, bottomTrailingRadius: 26, topTrailingRadius: 8)
                .stroke(Color.white.opacity(0.09), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.55), radius: 30, y: 18)
    }

    private var panelBackground: some View {
        UnevenRoundedRectangle(topLeadingRadius: 8, bottomLeadingRadius: 26, bottomTrailingRadius: 26, topTrailingRadius: 8)
            .fill(
                LinearGradient(
                    colors: [
                        Color(red: 0.055, green: 0.058, blue: 0.07).opacity(0.96),
                        Color.black.opacity(0.90),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )
            .overlay(
                UnevenRoundedRectangle(topLeadingRadius: 8, bottomLeadingRadius: 26, bottomTrailingRadius: 26, topTrailingRadius: 8)
                    .fill(.ultraThinMaterial.opacity(0.18))
            )
    }
}

struct TabButton: View {
    let title: String
    let icon: String
    var badge: Int? = nil
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 11, weight: .semibold))
                Text(title).font(.system(size: 11, weight: .bold, design: .rounded))
                if let badge {
                    Text("\(badge)")
                        .font(.system(size: 9, weight: .bold, design: .rounded))
                        .foregroundColor(isSelected ? .black : .white.opacity(0.65))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Capsule().fill(isSelected ? Color.green : Color.white.opacity(0.12)))
                }
            }
            .foregroundColor(isSelected ? .white : .white.opacity(0.45))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? Color.white.opacity(0.105) : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }
}

struct StatusPanel: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                HeroCard(
                    icon: monitor.currentStatus.status == "running" ? "bolt.fill" : "moon.zzz.fill",
                    title: monitor.currentStatus.status.uppercased(),
                    subtitle: monitor.currentStatus.active_agents.isEmpty ? "No active agents" : monitor.currentStatus.active_agents.joined(separator: " · "),
                    tint: statusColor
                )

                if !monitor.currentStatus.pipeline.isEmpty {
                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            SectionLabel("Pipeline")
                            Text(monitor.currentStatus.pipeline)
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .foregroundColor(.white.opacity(0.86))
                            ProgressView(value: monitor.currentStatus.progress)
                                .progressViewStyle(.linear)
                                .tint(.green)
                        }
                    }
                }

                ActionButton(title: "Quit Agentbox", icon: "power", tint: .red) {
                    NSApp.terminate(nil)
                }
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 16)
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

struct WorkspacePanel: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                DropZone(monitor: monitor)

                if monitor.workspaces.isEmpty {
                    EmptyWorkspaceCard()
                } else {
                    ForEach(monitor.workspaces) { workspace in
                        WorkspaceRow(workspace: workspace, monitor: monitor)
                    }

                    ActionButton(title: "Close All Workspaces", icon: "xmark.bin.fill", tint: .red.opacity(0.85)) {
                        monitor.deleteAllWorkspaces()
                    }
                }

                ActionButton(title: "Quit Agentbox", icon: "power", tint: .red) {
                    NSApp.terminate(nil)
                }
            }
            .padding(.horizontal, 14)
            .padding(.bottom, 16)
        }
    }
}

struct DropZone: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle()
                    .fill((monitor.isDragOver ? Color.green : Color.white).opacity(0.10))
                    .frame(width: 58, height: 58)
                Image(systemName: monitor.isDragOver ? "tray.and.arrow.down.fill" : "folder.badge.plus")
                    .font(.system(size: 25, weight: .semibold))
                    .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.50))
            }

            Text(monitor.isDragOver ? "Release to import folder" : monitor.lastDropMessage)
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.82))

            Text("Finder/Desktop folder → notch area")
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundColor(.white.opacity(0.36))
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 20)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(monitor.isDragOver ? Color.green.opacity(0.13) : Color.white.opacity(0.045))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(
                    monitor.isDragOver ? Color.green.opacity(0.95) : Color.white.opacity(0.10),
                    style: StrokeStyle(lineWidth: monitor.isDragOver ? 2 : 1, dash: monitor.isDragOver ? [] : [7, 5])
                )
        )
        .shadow(color: monitor.isDragOver ? .green.opacity(0.25) : .clear, radius: 18)
        .animation(.spring(response: 0.24, dampingFraction: 0.76), value: monitor.isDragOver)
    }
}

struct EmptyWorkspaceCard: View {
    var body: some View {
        GlassCard {
            HStack(spacing: 10) {
                Image(systemName: "rectangle.stack.badge.plus")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(.white.opacity(0.35))
                VStack(alignment: .leading, spacing: 3) {
                    Text("No workspaces")
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundColor(.white.opacity(0.82))
                    Text("Drop a folder to create an isolated Agentbox workspace.")
                        .font(.system(size: 10, weight: .medium, design: .rounded))
                        .foregroundColor(.white.opacity(0.42))
                }
                Spacer()
            }
        }
    }
}

struct WorkspaceRow: View {
    let workspace: WorkspaceItem
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.blue.opacity(0.18))
                            .frame(width: 36, height: 36)
                        Image(systemName: "folder.fill")
                            .font(.system(size: 17))
                            .foregroundColor(.blue.opacity(0.95))
                    }

                    VStack(alignment: .leading, spacing: 3) {
                        Text(workspace.name)
                            .font(.system(size: 13, weight: .bold, design: .rounded))
                            .foregroundColor(.white.opacity(0.92))
                            .lineLimit(1)
                        Text(workspace.folder_path)
                            .font(.system(size: 9, weight: .medium, design: .monospaced))
                            .foregroundColor(.white.opacity(0.32))
                            .lineLimit(1)
                    }

                    Spacer()

                    Button(action: { monitor.deleteWorkspace(id: workspace.id) }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundColor(.red.opacity(0.70))
                    }
                    .buttonStyle(.plain)
                }

                HStack(spacing: 6) {
                    ForEach(workspace.agents, id: \.self) { agent in
                        Chip(text: agent, color: .green)
                    }

                    Spacer(minLength: 4)

                    Chip(text: workspace.pipeline, color: .blue)
                }
            }
        }
    }
}

struct HeroCard: View {
    let icon: String
    let title: String
    let subtitle: String
    let tint: Color

    var body: some View {
        GlassCard {
            HStack(spacing: 12) {
                ZStack {
                    Circle().fill(tint.opacity(0.16)).frame(width: 46, height: 46)
                    Image(systemName: icon)
                        .font(.system(size: 19, weight: .bold))
                        .foregroundColor(tint)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.system(size: 15, weight: .bold, design: .rounded))
                        .foregroundColor(.white.opacity(0.92))
                    Text(subtitle)
                        .font(.system(size: 11, weight: .medium, design: .rounded))
                        .foregroundColor(.white.opacity(0.45))
                        .lineLimit(2)
                }

                Spacer()
            }
        }
    }
}

struct GlassCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(12)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: 18)
                    .fill(Color.white.opacity(0.055))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 18)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
    }
}

struct ActionButton: View {
    let title: String
    let icon: String
    let tint: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack {
                Image(systemName: icon)
                    .font(.system(size: 12, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                Spacer()
            }
            .foregroundColor(tint)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 14).fill(tint.opacity(0.11)))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(tint.opacity(0.16), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct Chip: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .foregroundColor(color.opacity(0.94))
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.13)))
            .overlay(Capsule().stroke(color.opacity(0.20), lineWidth: 1))
    }
}

struct SectionLabel: View {
    private let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .bold, design: .rounded))
            .foregroundColor(.white.opacity(0.38))
            .tracking(1.2)
    }
}

// MARK: - Mouse leave

final class MouseLeaveView: NSView {
    var onMouseLeave: (() -> Void)?

    override func mouseExited(with event: NSEvent) {
        onMouseLeave?()
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach { removeTrackingArea($0) }
        addTrackingArea(
            NSTrackingArea(
                rect: bounds,
                options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                owner: self,
                userInfo: nil
            )
        )
    }
}

struct MouseExitView: NSViewRepresentable {
    var onMouseLeave: () -> Void

    func makeNSView(context: Context) -> MouseLeaveView {
        let view = MouseLeaveView()
        view.onMouseLeave = onMouseLeave
        return view
    }

    func updateNSView(_ nsView: MouseLeaveView, context: Context) {
        nsView.onMouseLeave = onMouseLeave
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate {
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
