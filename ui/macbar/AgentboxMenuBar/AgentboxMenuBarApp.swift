// Agentbox — Clean single-window notch app with folder drag-drop
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

    @Published var isDragOver = false
    @Published var isExpanded = false
    @Published var selectedTab = 1
    @Published var lastDropMessage = "拖拽文件夹到此处"
    @Published var isCreating = false

    private var timer: Timer?
    private let baseURL = "http://localhost:18733"

    private var localWorkspacesFile: URL {
        URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".agentbox").appendingPathComponent("workspaces.json")
    }
    private let localAvailableAgents: [AgentOption] = [
        AgentOption(id: "claude", name: "Claude Code"),
        AgentOption(id: "codex", name: "Codex"),
        AgentOption(id: "aider", name: "Aider"),
        AgentOption(id: "goose", name: "Goose"),
        AgentOption(id: "opencode", name: "OpenCode"),
    ]
    private let localPipelineTemplates: [String: PipelineTemplate] = [
        "single-agent": PipelineTemplate(name: "Single Agent", desc: "One agent, direct task", steps: 1),
        "dev-pipeline": PipelineTemplate(name: "Dev Pipeline", desc: "Plan → Code → Review", steps: 3),
        "research-pipeline": PipelineTemplate(name: "Research Pipeline", desc: "Research → Summarize → Critique", steps: 3),
        "compare-pipeline": PipelineTemplate(name: "Compare Pipeline", desc: "Parallel agents → Synthesize", steps: 3),
    ]

    private func loadLocalWorkspaces() -> [WorkspaceItem] {
        guard let data = try? Data(contentsOf: localWorkspacesFile) else { return [] }
        return (try? JSONDecoder().decode([WorkspaceItem].self, from: data)) ?? []
    }

    private func saveLocalWorkspaces(_ items: [WorkspaceItem]) {
        try? FileManager.default.createDirectory(at: localWorkspacesFile.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let data = try? JSONEncoder().encode(items) {
            try? data.write(to: localWorkspacesFile)
        }
    }

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
        guard let url = URL(string: "\(baseURL)/workspaces") else {
            loadLocalWorkspacesIntoUI()
            return
        }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, error in
            guard let self,
                  let data,
                  error == nil,
                  let response = try? JSONDecoder().decode(WorkspaceListResponse.self, from: data) else {
                DispatchQueue.main.async { self?.loadLocalWorkspacesIntoUI() }
                return
            }
            DispatchQueue.main.async {
                self.workspaces = response.workspaces
                self.availableAgents = response.available_agents.isEmpty ? self.localAvailableAgents : response.available_agents
                self.pipelineTemplates = response.pipeline_templates.isEmpty ? self.localPipelineTemplates : response.pipeline_templates
            }
        }.resume()
    }

    private func loadLocalWorkspacesIntoUI() {
        workspaces = loadLocalWorkspaces()
        availableAgents = localAvailableAgents
        pipelineTemplates = localPipelineTemplates
    }

    func chooseFolderWithPanel() {
        let panel = NSOpenPanel()
        panel.title = "选择项目文件夹"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            selectedTab = 1
            isExpanded = true
            createWorkspace(folderPath: url.path)
        }
    }

    func createWorkspace(folderPath: String) {
        let folderName = URL(fileURLWithPath: folderPath).lastPathComponent
        lastDropMessage = "正在创建工作区: \(folderName)"
        isCreating = true

        guard FileManager.default.fileExists(atPath: folderPath) else {
            isCreating = false
            lastDropMessage = "文件夹不存在"
            return
        }

        let contextFile = URL(fileURLWithPath: folderPath).appendingPathComponent(".agentbox_context.md")
        if !FileManager.default.fileExists(atPath: contextFile.path) {
            try? "# Agentbox Shared Context\n".write(to: contextFile, atomically: true, encoding: .utf8)
        }

        guard let url = URL(string: "\(baseURL)/workspaces") else {
            createLocalWorkspace(folderPath: folderPath, folderName: folderName)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 5
        request.httpBody = try? JSONSerialization.data(withJSONObject: [
            "folder_path": folderPath,
            "agents": ["claude"],
            "pipeline": "single-agent",
        ])

        logAction("createWorkspace path=\(folderPath)")

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error = error as? URLError, error.code == .cannotConnectToHost || error.code == .cannotFindHost || error.code == .timedOut {
                    self.createLocalWorkspace(folderPath: folderPath, folderName: folderName)
                    return
                }
                self.isCreating = false
                if let error {
                    self.lastDropMessage = "错误: \(error.localizedDescription)"
                } else if let http = response as? HTTPURLResponse, http.statusCode >= 400 {
                    self.lastDropMessage = "服务端错误 (\(http.statusCode))"
                } else {
                    self.lastDropMessage = "✅ 工作区已创建: \(folderName)"
                }
                self.selectedTab = 1
                self.isExpanded = true
                self.fetchWorkspaces()
            }
        }.resume()
    }

    private func createLocalWorkspace(folderPath: String, folderName: String) {
        let wsId = "ws-\(UUID().uuidString.prefix(8))"
        let workspace = WorkspaceItem(
            id: wsId, name: folderName, folder_path: folderPath,
            agents: ["claude"], pipeline: "single-agent", status: "idle",
            created_at: ISO8601DateFormatter().string(from: Date())
        )
        var local = loadLocalWorkspaces()
        local.append(workspace)
        saveLocalWorkspaces(local)
        isCreating = false
        lastDropMessage = "✅ 工作区已创建: \(folderName)"
        selectedTab = 1
        isExpanded = true
        loadLocalWorkspacesIntoUI()
    }

    func deleteWorkspace(id: String) {
        var local = loadLocalWorkspaces()
        local.removeAll { $0.id == id }
        saveLocalWorkspaces(local)
        guard let url = URL(string: "\(baseURL)/workspaces/\(id)") else {
            loadLocalWorkspacesIntoUI()
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.timeoutInterval = 3
        URLSession.shared.dataTask(with: request) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.fetchWorkspaces() }
        }.resume()
    }

    func deleteAllWorkspaces() {
        for id in workspaces.map(\.id) { deleteWorkspace(id: id) }
    }

    // MARK: - Agent Quick Launch (uses `ag` CLI to start Docker sandbox)

    func launchAgent(workspace: WorkspaceItem, agentType: String) {
        logAction("launchAgent ws=\(workspace.id) agent=\(agentType) path=\(workspace.folder_path)")

        // Try backend first
        if let url = URL(string: "\(baseURL)/agent/open") {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 5
            request.httpBody = try? JSONSerialization.data(withJSONObject: [
                "agent": agentType,
                "workspace": workspace.id,
                "folder_path": workspace.folder_path,
            ])

            URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let error = error as? URLError, error.code == .cannotConnectToHost || error.code == .cannotFindHost || error.code == .timedOut {
                        self.launchAgentViaTerminal(workspace: workspace, agentType: agentType)
                    } else if let http = response as? HTTPURLResponse, http.statusCode < 400 {
                        self.lastDropMessage = "🚀 \(agentType) 已启动"
                        self.updateWorkspaceStatus(workspaceId: workspace.id, status: "running")
                    } else {
                        self.launchAgentViaTerminal(workspace: workspace, agentType: agentType)
                    }
                }
            }.resume()
        } else {
            launchAgentViaTerminal(workspace: workspace, agentType: agentType)
        }
    }

    /// Launch agent via Terminal by calling `ag <agent> -p <path>`
    /// This creates a Docker sandbox, tmux session, and attaches to it.
    private func launchAgentViaTerminal(workspace: WorkspaceItem, agentType: String) {
        let escapedPath = workspace.folder_path.replacingOccurrences(of: "'", with: "'\\''")
        let script = """
        tell application "Terminal"
            activate
            do script "cd '\(escapedPath)' && ag \(agentType) -p '\(escapedPath)'"
        end tell
        """

        if let appleScript = NSAppleScript(source: script) {
            var error: NSDictionary?
            appleScript.executeAndReturnError(&error)
            if let error {
                logAction("launchAgent AppleScript error: \(error)")
                // Fallback: open Terminal and run command manually
                NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"), configuration: NSWorkspace.OpenConfiguration())
            }
        }

        lastDropMessage = "🚀 \(agentType) 沙盒启动中..."
        logAction("launchAgent via ag CLI agent=\(agentType)")
        updateWorkspaceStatus(workspaceId: workspace.id, status: "running")
    }

    func updateWorkspaceStatus(workspaceId: String, status: String) {
        var local = loadLocalWorkspaces()
        for i in local.indices where local[i].id == workspaceId {
            local[i].status = status
        }
        saveLocalWorkspaces(local)

        if let url = URL(string: "\(baseURL)/workspaces/\(workspaceId)") {
            var request = URLRequest(url: url)
            request.httpMethod = "PUT"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = 3
            request.httpBody = try? JSONSerialization.data(withJSONObject: ["status": status])
            URLSession.shared.dataTask(with: request) { [weak self] _, _, _ in
                DispatchQueue.main.async { self?.fetchWorkspaces() }
            }.resume()
        }
        loadLocalWorkspacesIntoUI()
    }

    func logAction(_ message: String) {
        let line = "[\(Date())] \(message)\n"
        let url = URL(fileURLWithPath: "/tmp/agentbox_notch_drag.log")
        if let data = line.data(using: .utf8) {
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

// MARK: - Drag Coordinator

final class NotchDragCoordinator: NSObject {
    let monitor: StatusMonitor
    init(monitor: StatusMonitor) { self.monitor = monitor }

    static let dragTypes: [NSPasteboard.PasteboardType] = [
        .fileURL,
        NSPasteboard.PasteboardType("NSFilenamesPboardType"),
        NSPasteboard.PasteboardType("public.file-url"),
    ]

    func extractFolderPaths(_ pasteboard: NSPasteboard) -> [String] {
        var candidates: [String] = []
        if let files = pasteboard.propertyList(forType: NSPasteboard.PasteboardType("NSFilenamesPboardType")) as? [String] {
            candidates.append(contentsOf: files)
        }
        if let urls = pasteboard.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [NSURL] {
            for url in urls { if let path = url.path { candidates.append(path) } }
        }
        for type in Self.dragTypes {
            if let value = pasteboard.string(forType: type) {
                if let url = URL(string: value), url.isFileURL { candidates.append(url.path) }
                else if value.hasPrefix("/") { candidates.append(value) }
            }
        }
        let directories = Array(Set(candidates)).filter { path in
            var isDir: ObjCBool = false
            return FileManager.default.fileExists(atPath: path, isDirectory: &isDir) && isDir.boolValue
        }
        monitor.logAction("drag extract: candidates=\(candidates.count) dirs=\(directories)")
        return directories
    }
}

// MARK: - Drag-receiving hosting view

final class DragReceivingHostingView: NSHostingView<AnyView> {
    private let coordinator: NotchDragCoordinator

    init(rootView: AnyView, coordinator: NotchDragCoordinator) {
        self.coordinator = coordinator
        super.init(rootView: rootView)
        registerForDraggedTypes(NotchDragCoordinator.dragTypes)
    }

    @available(*, unavailable)
    required init(rootView: AnyView) { fatalError() }
    required init?(coder: NSCoder) { fatalError() }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        let paths = coordinator.extractFolderPaths(sender.draggingPasteboard)
        DispatchQueue.main.async {
            self.coordinator.monitor.isDragOver = true
            self.coordinator.monitor.isExpanded = true
            self.coordinator.monitor.selectedTab = 1
            self.coordinator.monitor.lastDropMessage = paths.isEmpty ? "释放以检查" : "释放以创建工作区"
        }
        return .copy
    }

    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation { .copy }

    override func draggingExited(_ sender: NSDraggingInfo?) {
        DispatchQueue.main.async {
            self.coordinator.monitor.isDragOver = false
            self.coordinator.monitor.lastDropMessage = "拖拽文件夹到此处"
        }
    }

    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool { true }

    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let paths = coordinator.extractFolderPaths(sender.draggingPasteboard)
        DispatchQueue.main.async { self.coordinator.monitor.isDragOver = false }
        guard let first = paths.first else {
            DispatchQueue.main.async {
                self.coordinator.monitor.lastDropMessage = "拖入项不包含文件夹"
            }
            return false
        }
        DispatchQueue.main.async {
            self.coordinator.monitor.isExpanded = true
            self.coordinator.monitor.selectedTab = 1
            self.coordinator.monitor.createWorkspace(folderPath: first)
        }
        return true
    }
}

// MARK: - Visible Panel

final class VisiblePanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

// MARK: - Window Manager

final class NotchManager {
    static let shared = NotchManager()
    var window: NSPanel?
    let monitor = StatusMonitor()

    private let windowWidth: CGFloat = 380
    private let collapsedHeight: CGFloat = 44
    private let expandedHeight: CGFloat = 520

    func createWindow() {
        guard let screen = NSScreen.main else { return }
        let screenFrame = screen.frame
        let rect = NSRect(
            x: screenFrame.midX - windowWidth / 2,
            y: screenFrame.maxY - collapsedHeight,
            width: windowWidth,
            height: collapsedHeight
        )

        let panel = VisiblePanel(
            contentRect: rect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        panel.ignoresMouseEvents = false
        panel.isMovableByWindowBackground = false
        panel.hidesOnDeactivate = false

        let coordinator = NotchDragCoordinator(monitor: monitor)
        let rootView = AnyView(NotchContentView(monitor: monitor))
        panel.contentView = DragReceivingHostingView(rootView: rootView, coordinator: coordinator)

        panel.orderFrontRegardless()
        window = panel
        monitor.logAction("Window created frame=\(rect)")
    }

    func updateWindowFrame(expanded: Bool) {
        guard let window, let screen = NSScreen.main else { return }
        let screenFrame = screen.frame
        let height = expanded ? expandedHeight : collapsedHeight
        let rect = NSRect(
            x: screenFrame.midX - windowWidth / 2,
            y: screenFrame.maxY - height,
            width: windowWidth,
            height: height
        )
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.3
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            window.animator().setFrame(rect, display: true)
        }
    }
}

// MARK: - SwiftUI UI

struct NotchContentView: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 0) {
            NotchCapsule(monitor: monitor)
                .padding(.top, 2)

            if monitor.isExpanded {
                NotchPanelContent(monitor: monitor)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .frame(width: 380, alignment: .top)
        .frame(maxHeight: .infinity, alignment: .top)
        .onChange(of: monitor.isExpanded) { _, expanded in
            NotchManager.shared.updateWindowFrame(expanded: expanded)
        }
    }
}

// MARK: - Notch Capsule

struct NotchCapsule: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle().fill(statusColor.opacity(0.25)).frame(width: 20, height: 20)
                Circle().fill(statusColor).frame(width: 9, height: 9)
                    .shadow(color: statusColor.opacity(0.6), radius: 4)
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: monitor.isDragOver ? 13 : 11, weight: .bold, design: .rounded))
                    .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.92))
                    .tracking(monitor.isDragOver ? 1.5 : 1.0)
                if monitor.isDragOver {
                    Text("释放以创建工作区")
                        .font(.system(size: 9, weight: .medium, design: .rounded))
                        .foregroundColor(.green.opacity(0.85))
                }
            }

            Spacer(minLength: 0)

            Image(systemName: monitor.isDragOver ? "arrow.down.circle.fill" : (monitor.isExpanded ? "chevron.up" : "sparkles"))
                .font(.system(size: monitor.isDragOver ? 18 : 13, weight: .semibold))
                .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.55))
        }
        .padding(.horizontal, monitor.isDragOver ? 20 : 16)
        .frame(width: monitor.isDragOver ? 320 : 230, height: monitor.isDragOver ? 60 : 38)
        .background(capsuleBackground)
        .overlay(
            RoundedRectangle(cornerRadius: monitor.isDragOver ? 30 : 19)
                .stroke(monitor.isDragOver ? Color.green.opacity(0.9) : Color.white.opacity(0.12), lineWidth: monitor.isDragOver ? 2 : 1)
        )
        .shadow(color: monitor.isDragOver ? .green.opacity(0.35) : .black.opacity(0.5), radius: monitor.isDragOver ? 24 : 16, y: 6)
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
        if monitor.isDragOver { return "拖入文件夹" }
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
        RoundedRectangle(cornerRadius: monitor.isDragOver ? 30 : 19)
            .fill(
                LinearGradient(
                    colors: monitor.isDragOver
                        ? [Color.green.opacity(0.25), Color.black.opacity(0.90), Color.green.opacity(0.15)]
                        : [Color.black.opacity(0.96), Color(red: 0.04, green: 0.045, blue: 0.06).opacity(0.94)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .overlay(RoundedRectangle(cornerRadius: monitor.isDragOver ? 30 : 19).fill(.ultraThinMaterial.opacity(0.15)))
    }
}

// MARK: - Panel Content

struct NotchPanelContent: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TabButton(title: "状态", icon: "waveform.path.ecg", isSelected: monitor.selectedTab == 0) { monitor.selectedTab = 0 }
                TabButton(title: "工作区", icon: "folder.fill", badge: monitor.workspaces.count, isSelected: monitor.selectedTab == 1) { monitor.selectedTab = 1 }
            }
            .padding(.top, 14)
            .padding(.horizontal, 16)
            .padding(.bottom, 10)

            if monitor.selectedTab == 0 {
                StatusTab(monitor: monitor)
            } else {
                WorkspaceTab(monitor: monitor)
            }
        }
        .frame(width: 360)
        .frame(maxHeight: 460)
        .background(panelBackground)
        .overlay(
            UnevenRoundedRectangle(topLeadingRadius: 6, bottomLeadingRadius: 28, bottomTrailingRadius: 28, topTrailingRadius: 6)
                .stroke(Color.white.opacity(0.10), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.6), radius: 32, y: 20)
        .onHover { hovering in
            if !hovering && monitor.isExpanded && !monitor.isDragOver {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                    monitor.isExpanded = false
                }
            }
        }
    }

    private var panelBackground: some View {
        UnevenRoundedRectangle(topLeadingRadius: 6, bottomLeadingRadius: 28, bottomTrailingRadius: 28, topTrailingRadius: 6)
            .fill(
                LinearGradient(
                    colors: [Color(red: 0.06, green: 0.062, blue: 0.075).opacity(0.97), Color.black.opacity(0.92)],
                    startPoint: .top, endPoint: .bottom
                )
            )
            .overlay(
                UnevenRoundedRectangle(topLeadingRadius: 6, bottomLeadingRadius: 28, bottomTrailingRadius: 28, topTrailingRadius: 6)
                    .fill(.ultraThinMaterial.opacity(0.22))
            )
    }
}

// MARK: - Tab Button

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
                Text(title).font(.system(size: 12, weight: .bold, design: .rounded))
                if let badge {
                    Text("\(badge)")
                        .font(.system(size: 9, weight: .bold, design: .rounded))
                        .foregroundColor(isSelected ? .black : .white.opacity(0.7))
                        .padding(.horizontal, 6).padding(.vertical, 1)
                        .background(Capsule().fill(isSelected ? Color.green : Color.white.opacity(0.14)))
                }
            }
            .foregroundColor(isSelected ? .white : .white.opacity(0.45))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 13).fill(isSelected ? Color.white.opacity(0.12) : Color.clear))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Status Tab

struct StatusTab: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                HeroCard(icon: monitor.currentStatus.status == "running" ? "bolt.fill" : "moon.zzz.fill",
                         title: monitor.currentStatus.status.uppercased(),
                         subtitle: monitor.currentStatus.active_agents.isEmpty ? "无活跃 Agent" : monitor.currentStatus.active_agents.joined(separator: " · "),
                         tint: statusColor)

                if !monitor.currentStatus.pipeline.isEmpty {
                    GlassCard {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                SectionLabel("流水线")
                                Spacer()
                                Text("\(Int(monitor.currentStatus.progress * 100))%").font(.system(size: 11, weight: .bold, design: .rounded)).foregroundColor(.green)
                            }
                            Text(monitor.currentStatus.pipeline).font(.system(size: 13, weight: .semibold, design: .rounded)).foregroundColor(.white.opacity(0.88))
                            ProgressView(value: monitor.currentStatus.progress).tint(.green)
                        }
                    }
                }

                if !monitor.currentStatus.alerts.isEmpty {
                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            SectionLabel("告警")
                            ForEach(monitor.currentStatus.alerts) { alert in
                                HStack(spacing: 8) {
                                    Circle().fill(alert.level == "error" ? .red : .orange).frame(width: 7, height: 7)
                                    Text(alert.message).font(.system(size: 11, weight: .medium)).foregroundColor(.white.opacity(0.75)).lineLimit(2)
                                    Spacer()
                                }
                            }
                        }
                    }
                }

                ActionButton(title: "退出 Agentbox", icon: "power", tint: .red) { NSApp.terminate(nil) }
            }
            .padding(.horizontal, 16).padding(.bottom, 18)
        }
    }

    private var statusColor: Color {
        switch monitor.currentStatus.status { case "running": .yellow; case "degraded": .red; default: .green }
    }
}

// MARK: - Workspace Tab

struct WorkspaceTab: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                DropZoneCard(monitor: monitor)

                if monitor.isCreating { CreatingCard() }

                if monitor.workspaces.isEmpty && !monitor.isCreating {
                    EmptyWorkspaceCard()
                } else {
                    ForEach(monitor.workspaces) { ws in
                        WorkspaceRow(workspace: ws, monitor: monitor)
                    }
                    if !monitor.workspaces.isEmpty {
                        ActionButton(title: "关闭所有工作区", icon: "xmark.bin.fill", tint: .red.opacity(0.85)) { monitor.deleteAllWorkspaces() }
                    }
                }

                ActionButton(title: "退出 Agentbox", icon: "power", tint: .red) { NSApp.terminate(nil) }
            }
            .padding(.horizontal, 16).padding(.bottom, 18)
        }
    }
}

// MARK: - Drop Zone Card

struct DropZoneCard: View {
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle().fill((monitor.isDragOver ? Color.green : Color.white).opacity(0.10)).frame(width: 62, height: 62)
                if monitor.isDragOver {
                    Circle().stroke(Color.green.opacity(0.5), lineWidth: 2).frame(width: 62, height: 62)
                        .scaleEffect(monitor.isDragOver ? 1.3 : 1.0).opacity(monitor.isDragOver ? 0 : 1)
                        .animation(.easeOut(duration: 1.0).repeatForever(autoreverses: false), value: monitor.isDragOver)
                }
                Image(systemName: monitor.isDragOver ? "tray.and.arrow.down.fill" : "folder.badge.plus")
                    .font(.system(size: 27, weight: .semibold))
                    .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.55))
                    .scaleEffect(monitor.isDragOver ? 1.1 : 1.0)
            }

            Text(monitor.isDragOver ? "释放以导入文件夹" : monitor.lastDropMessage)
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundColor(monitor.isDragOver ? .green : .white.opacity(0.85))
                .multilineTextAlignment(.center).lineLimit(2)

            Text("拖拽文件夹至此，或点击选择")
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundColor(.white.opacity(0.38))
        }
        .frame(maxWidth: .infinity).padding(.vertical, 22)
        .background(RoundedRectangle(cornerRadius: 22).fill(monitor.isDragOver ? Color.green.opacity(0.14) : Color.white.opacity(0.05)))
        .overlay(
            RoundedRectangle(cornerRadius: 22)
                .stroke(monitor.isDragOver ? Color.green.opacity(0.95) : Color.white.opacity(0.10),
                        style: StrokeStyle(lineWidth: monitor.isDragOver ? 2 : 1, dash: monitor.isDragOver ? [] : [8, 5]))
        )
        .shadow(color: monitor.isDragOver ? .green.opacity(0.30) : .clear, radius: 20)
        .contentShape(Rectangle())
        .onTapGesture { monitor.chooseFolderWithPanel() }
        .animation(.spring(response: 0.25, dampingFraction: 0.76), value: monitor.isDragOver)
    }
}

// MARK: - Creating Card

struct CreatingCard: View {
    var body: some View {
        GlassCard {
            HStack(spacing: 12) {
                ProgressView().progressViewStyle(.circular).scaleEffect(0.8).tint(.green)
                Text("正在创建工作区...").font(.system(size: 13, weight: .semibold, design: .rounded)).foregroundColor(.white.opacity(0.85))
                Spacer()
            }
        }
    }
}

// MARK: - Empty Workspace

struct EmptyWorkspaceCard: View {
    var body: some View {
        GlassCard {
            HStack(spacing: 12) {
                Image(systemName: "rectangle.stack.badge.plus").font(.system(size: 20, weight: .semibold)).foregroundColor(.white.opacity(0.38))
                VStack(alignment: .leading, spacing: 4) {
                    Text("暂无工作区").font(.system(size: 13, weight: .bold, design: .rounded)).foregroundColor(.white.opacity(0.85))
                    Text("拖拽文件夹至此处即可创建隔离的 Agentbox 工作区").font(.system(size: 10, weight: .medium, design: .rounded)).foregroundColor(.white.opacity(0.44))
                }
                Spacer()
            }
        }
    }
}

// MARK: - Workspace Row

struct WorkspaceRow: View {
    let workspace: WorkspaceItem
    @ObservedObject var monitor: StatusMonitor

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 11)
                            .fill(LinearGradient(colors: [Color.blue.opacity(0.22), Color.blue.opacity(0.10)], startPoint: .topLeading, endPoint: .bottomTrailing))
                            .frame(width: 40, height: 40)
                        Image(systemName: "folder.fill").font(.system(size: 18)).foregroundColor(.blue.opacity(0.95))
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(workspace.name).font(.system(size: 14, weight: .bold, design: .rounded)).foregroundColor(.white.opacity(0.92)).lineLimit(1)
                        Text(workspace.folder_path).font(.system(size: 9, weight: .medium, design: .monospaced)).foregroundColor(.white.opacity(0.35)).lineLimit(1).truncationMode(.middle)
                    }
                    Spacer()
                    Button(action: { monitor.deleteWorkspace(id: workspace.id) }) {
                        Image(systemName: "xmark.circle.fill").font(.system(size: 18, weight: .semibold)).foregroundColor(.red.opacity(0.65))
                    }.buttonStyle(.plain)
                }

                HStack(spacing: 6) {
                    ForEach(workspace.agents, id: \.self) { Chip(text: $0, color: .green) }
                    Spacer(minLength: 4)
                    Chip(text: workspace.pipeline, color: .blue)
                    StatusChip(status: workspace.status)
                }

                VStack(spacing: 8) {
                    HStack(spacing: 8) {
                        AgentLaunchButton(label: "Claude", color: .indigo) { monitor.launchAgent(workspace: workspace, agentType: "claude") }
                        AgentLaunchButton(label: "Codex", color: .cyan) { monitor.launchAgent(workspace: workspace, agentType: "codex") }
                        AgentLaunchButton(label: "Aider", color: .pink) { monitor.launchAgent(workspace: workspace, agentType: "aider") }
                    }
                    HStack(spacing: 8) {
                        AgentLaunchButton(label: "Goose", color: .orange) { monitor.launchAgent(workspace: workspace, agentType: "goose") }
                        AgentLaunchButton(label: "OpenCode", color: .teal) { monitor.launchAgent(workspace: workspace, agentType: "opencode") }
                        AgentLaunchButton(label: "Shell", color: .gray) { monitor.launchAgent(workspace: workspace, agentType: "shell") }
                    }
                }
            }
        }
    }
}

struct AgentLaunchButton: View {
    let label: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: "play.fill").font(.system(size: 9, weight: .bold))
                Text(label).font(.system(size: 11, weight: .bold, design: .rounded))
            }
            .foregroundColor(color)
            .frame(maxWidth: .infinity).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 11).fill(color.opacity(0.12)))
            .overlay(RoundedRectangle(cornerRadius: 11).stroke(color.opacity(0.20), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Hero Card

struct HeroCard: View {
    let icon: String; let title: String; let subtitle: String; let tint: Color
    var body: some View {
        GlassCard {
            HStack(spacing: 14) {
                ZStack {
                    Circle().fill(tint.opacity(0.18)).frame(width: 50, height: 50)
                    Image(systemName: icon).font(.system(size: 21, weight: .bold)).foregroundColor(tint)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.system(size: 16, weight: .bold, design: .rounded)).foregroundColor(.white.opacity(0.92))
                    Text(subtitle).font(.system(size: 11, weight: .medium, design: .rounded)).foregroundColor(.white.opacity(0.48)).lineLimit(2)
                }
                Spacer()
            }
        }
    }
}

// MARK: - Reusable Components

struct GlassCard<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        content
            .padding(14).frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 18).fill(.ultraThinMaterial.opacity(0.35)))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color.white.opacity(0.10), lineWidth: 1))
    }
}

struct ActionButton: View {
    let title: String; let icon: String; let tint: Color; let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack {
                Image(systemName: icon).font(.system(size: 13, weight: .bold))
                Text(title).font(.system(size: 12, weight: .bold, design: .rounded))
                Spacer()
            }
            .foregroundColor(tint)
            .padding(.horizontal, 14).padding(.vertical, 11)
            .background(RoundedRectangle(cornerRadius: 15).fill(tint.opacity(0.12)))
            .overlay(RoundedRectangle(cornerRadius: 15).stroke(tint.opacity(0.18), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}

struct Chip: View {
    let text: String; let color: Color
    var body: some View {
        Text(text).font(.system(size: 9, weight: .bold, design: .monospaced))
            .foregroundColor(color.opacity(0.95))
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.14)))
            .overlay(Capsule().stroke(color.opacity(0.22), lineWidth: 1))
    }
}

struct StatusChip: View {
    let status: String
    var body: some View {
        let color: Color = {
            switch status.lowercased() { case "running", "active": .green; case "stopped", "idle": .gray; case "error", "failed": .red; default: .gray }
        }()
        HStack(spacing: 3) {
            Circle().fill(color).frame(width: 5, height: 5)
            Text(status).font(.system(size: 8, weight: .bold, design: .rounded))
        }
        .foregroundColor(color.opacity(0.95))
        .padding(.horizontal, 7).padding(.vertical, 4)
        .background(Capsule().fill(color.opacity(0.12)))
    }
}

struct SectionLabel: View {
    private let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased()).font(.system(size: 9, weight: .bold, design: .rounded)).foregroundColor(.white.opacity(0.40)).tracking(1.3)
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate {
    var notchManager = NotchManager.shared

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        notchManager.createWindow()
        notchManager.monitor.startMonitoring()
        notchManager.monitor.logAction("App launched successfully")
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }
}

@main
struct AgentboxNotchApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    var body: some Scene { Settings {} }
}