// Enhanced Multi-Agent System Frontend Application
class EnhancedMultiAgentApp {
    constructor() {
        this.state = {
            agents: {},
            messages: [],
            systemRunning: false,
            currentProject: null,
            taskQueue: {
                pending: 0,
                in_progress: 0,
                completed: 0,
                failed: 0,
            },
            metrics: {},
            currentView: "dashboard",
            notifications: [],
        };

        this.socket = null;
        this.updateInterval = null;
        this.connected = false;
        this.retryCount = 0;
        this.maxRetries = 5;

        this.init();
    }

    init() {
        console.log("🚀 Initializing Enhanced Multi-Agent System");
        this.setupEventListeners();
        this.setupSocketIO();
        this.setupNavigation();
        this.setupNotifications();
        this.setupKeyboardShortcuts();
        this.loadInitialData();
        this.startPeriodicUpdates();
    }

    setupSocketIO() {
        this.socket = io({
            transports: ["websocket", "polling"],
            upgrade: true,
            rememberUpgrade: true,
        });

        this.socket.on("connect", () => {
            console.log("✅ Connected to server");
            this.connected = true;
            this.retryCount = 0;
            this.updateConnectionStatus(true);
            this.showNotification("Connected to server", "success");
        });

        this.socket.on("disconnect", () => {
            console.log("❌ Disconnected from server");
            this.connected = false;
            this.updateConnectionStatus(false);
            this.showNotification("Connection lost", "error");
            this.attemptReconnection();
        });

        this.socket.on("system_update", (data) => {
            this.handleSystemUpdate(data);
        });

        this.socket.on("project_started", (data) => {
            this.handleProjectStarted(data);
        });

        this.socket.on("project_stopped", () => {
            this.handleProjectStopped();
        });

        this.socket.on("message_sent", (message) => {
            this.handleNewMessage(message);
        });

        this.socket.on("project_reviewed", (data) => {
            this.handleProjectReviewed(data);
        });

        this.socket.on("connect_error", (error) => {
            console.error("Connection error:", error);
            this.updateConnectionStatus(false);
        });
    }

    attemptReconnection() {
        if (this.retryCount < this.maxRetries) {
            this.retryCount++;
            const delay = Math.min(1000 * Math.pow(2, this.retryCount), 30000);

            setTimeout(() => {
                console.log(
                    `🔄 Attempting reconnection (${this.retryCount}/${this.maxRetries})`
                );
                this.socket.connect();
            }, delay);
        } else {
            this.showNotification(
                "Connection failed. Please refresh the page.",
                "error",
                0
            );
        }
    }

    setupEventListeners() {
        // Project controls
        const startBtn = document.getElementById("start-project");
        const stopBtn = document.getElementById("stop-project");
        const pauseBtn = document.getElementById("pause-project");
        const downloadBtn = document.getElementById("download-project");

        if (startBtn) {
            startBtn.addEventListener("click", () => this.startProject());
        }
        if (stopBtn) {
            stopBtn.addEventListener("click", () => this.stopProject());
        }
        if (pauseBtn) {
            pauseBtn.addEventListener("click", () => this.pauseProject());
        }
        if (downloadBtn) {
            downloadBtn.addEventListener("click", () => this.downloadProject());
        }

        // Template buttons
        document.querySelectorAll(".template-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
                const template = btn.dataset.template;
                this.loadTemplate(template);
            });
        });

        // Action buttons
        const refreshBtn = document.getElementById("refresh-dashboard");
        const exportBtn = document.getElementById("export-logs");
        const performanceBtn = document.getElementById("performance-report");

        if (refreshBtn) {
            refreshBtn.addEventListener("click", () => this.refreshDashboard());
        }
        if (exportBtn) {
            exportBtn.addEventListener("click", () => this.exportLogs());
        }
        if (performanceBtn) {
            performanceBtn.addEventListener("click", () =>
                this.showPerformanceReport()
            );
        }

        // Form submissions
        const projectForm = document.getElementById("project-form");
        if (projectForm) {
            projectForm.addEventListener("submit", (e) => {
                e.preventDefault();
                this.startProject();
            });
        }

        // Search and filters
        const agentSearch = document.getElementById("agent-search");
        const agentFilter = document.getElementById("agent-filter");
        const messageFilter = document.getElementById("message-filter");
        const refreshFiles = document.getElementById("refresh-files");

        if (agentSearch) {
            agentSearch.addEventListener("input", (e) => {
                this.filterAgents(e.target.value);
            });
        }
        if (agentFilter) {
            agentFilter.addEventListener("change", (e) => {
                this.filterAgents(null, e.target.value);
            });
        }
        if (messageFilter) {
            messageFilter.addEventListener("change", (e) => {
                this.filterMessages(e.target.value);
            });
        }
        if (refreshFiles) {
            refreshFiles.addEventListener("click", () => {
                this.loadProjectFiles();
            });
        }

        const downloadAllFiles = document.getElementById("download-all-files");
        if (downloadAllFiles) {
            downloadAllFiles.addEventListener("click", () => {
                this.downloadProject();
            });
        }
    }

    setupNavigation() {
        document.querySelectorAll(".nav-tab").forEach((tab) => {
            tab.addEventListener("click", (e) => {
                e.preventDefault();
                const viewName = tab.dataset.view;
                this.switchView(viewName);
            });
        });
    }

    setupNotifications() {
        // Create notification container if it doesn't exist
        if (!document.getElementById("notification-container")) {
            const container = document.createElement("div");
            container.id = "notification-container";
            container.className = "notification-container";
            document.body.appendChild(container);
        }
    }

    setupKeyboardShortcuts() {
        document.addEventListener("keydown", (e) => {
            // Ctrl+Enter to start project
            if (e.ctrlKey && e.key === "Enter") {
                e.preventDefault();
                this.startProject();
            }
            // Escape to close modals
            if (e.key === "Escape") {
                this.closeAllModals();
            }
            // Ctrl+R to refresh dashboard
            if (e.ctrlKey && e.key === "r") {
                e.preventDefault();
                this.refreshDashboard();
            }
        });
    }

    async loadInitialData() {
        try {
            const response = await fetch("/api/agents");
            const data = await response.json();

            if (data.success) {
                this.state.agents = data.agents;
                this.state.systemRunning = data.system_running;
                this.state.currentProject = data.current_project;
                this.state.taskQueue = data.task_queue;
                this.updateUI();
            } else {
                throw new Error(data.error || "Failed to load agents");
            }
        } catch (error) {
            console.error("Failed to load initial data:", error);
            this.showNotification("Failed to load initial data", "error");
        }
    }

    startPeriodicUpdates() {
        this.updateInterval = setInterval(() => {
            if (this.connected) {
                this.loadMetrics();

                // Refresh files if files view is active
                if (this.state.currentView === "files") {
                    this.loadProjectFiles();
                }
            }
        }, 5000); // Update every 5 seconds
    }

    async loadMetrics() {
        try {
            const response = await fetch("/api/metrics");
            const data = await response.json();

            if (data.success) {
                this.state.metrics = data.metrics;
                this.updateMetricsDisplay();
            }
        } catch (error) {
            console.error("Failed to load metrics:", error);
        }
    }

    handleSystemUpdate(data) {
        this.state.agents = data.agents;
        this.state.messages = data.messages;
        this.state.taskQueue = data.task_queue;
        this.state.systemRunning = data.system_running;
        this.state.currentProject = data.current_project;
        this.state.metrics = data.metrics;

        this.updateUI();
    }

    handleProjectStarted(data) {
        this.state.currentProject = data.project;
        this.state.systemRunning = true;
        this.state.agents = data.agents;

        this.updateProjectControls();
        this.updateUI();
        this.showNotification("Project started successfully!", "success");
    }

    handleProjectStopped() {
        this.state.systemRunning = false;
        this.updateProjectControls();
        this.showNotification("Project stopped", "info");
    }

    handleNewMessage(message) {
        this.state.messages.unshift(message);

        // Keep only last 100 messages
        if (this.state.messages.length > 100) {
            this.state.messages = this.state.messages.slice(0, 100);
        }

        this.updateMessagesDisplay();

        // Show notification for important messages
        if (message.type === "task_completion" || message.type === "error") {
            this.showNotification(
                `${this.getAgentName(
                    message.from_agent_id
                )}: ${message.content.substring(0, 50)}...`,
                message.type === "error" ? "error" : "info"
            );
        }
    }

    handleProjectReviewed(data) {
        this.showNotification(
            `Project completed with ${data.files_count} files! Ready for download.`,
            "success"
        );
        // Refresh files display
        this.loadProjectFiles();
    }

    updateUI() {
        this.updateAgentsDisplay();
        this.updateMessagesDisplay();
        this.updateTaskQueueDisplay();
        this.updateMetricsDisplay();
        this.updateProjectStatus();
    }

    updateAgentsDisplay() {
        const agentsGrid = document.getElementById("agents-grid");
        if (!agentsGrid) return;

        agentsGrid.innerHTML = "";

        Object.values(this.state.agents).forEach((agent) => {
            const agentCard = this.createAgentCard(agent);
            agentsGrid.appendChild(agentCard);
        });
    }

    createAgentCard(agent) {
        const card = document.createElement("div");
        card.className = `agent-card ${agent.status} ${
            agent.is_active ? "active" : "inactive"
        }`;
        card.dataset.agentId = agent.id;

        const statusColors = {
            idle: "bg-gray-500",
            working: "bg-yellow-500",
            completed: "bg-green-500",
            error: "bg-red-500",
            reviewing: "bg-blue-500",
        };

        const performanceScore = this.calculatePerformanceScore(agent);
        const lastActivity = this.getRelativeTime(agent.last_activity);

        card.innerHTML = `
            <div class="agent-header">
                <div class="agent-info">
                    <h3 class="agent-name">${agent.name}</h3>
                    <span class="agent-role">${agent.role}</span>
                </div>
                <div class="agent-status">
                    <div class="status-indicator ${agent.status}">
                        <span class="status-dot"></span>
                        <span class="status-text">${this.formatStatus(
                            agent.status
                        )}</span>
                    </div>
                </div>
            </div>
            
            <div class="agent-content">
                <div class="agent-specialty">
                    <p>${agent.specialty}</p>
                </div>
                
                <div class="agent-metrics">
                    <div class="metric-item">
                        <span class="metric-label">Tasks</span>
                        <span class="metric-value">${
                            agent.performance_metrics.tasks_completed
                        }</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Score</span>
                        <span class="metric-value">${performanceScore}%</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">Last Active</span>
                        <span class="metric-value">${lastActivity}</span>
                    </div>
                </div>
                
                <div class="agent-skills">
                    ${agent.skills
                        .map(
                            (skill) => `<span class="skill-tag">${skill}</span>`
                        )
                        .join("")}
                </div>
                
                <div class="agent-actions">
                    <button class="btn btn-sm btn-outline" onclick="app.showAgentDetails('${
                        agent.id
                    }')">
                        <i class="fas fa-info-circle"></i>
                        Details
                    </button>
                    <button class="btn btn-sm btn-outline" onclick="app.toggleAgent('${
                        agent.id
                    }')">
                        <i class="fas fa-power-off"></i>
                        ${agent.is_active ? "Pause" : "Resume"}
                    </button>
                </div>
            </div>
        `;

        return card;
    }

    updateMessagesDisplay() {
        const messagesList = document.getElementById("messages-list");
        if (!messagesList) return;

        messagesList.innerHTML = "";

        this.state.messages.slice(0, 50).forEach((message, index) => {
            const messageItem = this.createMessageItem(message);
            messagesList.appendChild(messageItem);
        });

        // Auto-scroll to bottom
        messagesList.scrollTop = messagesList.scrollHeight;
    }

    createMessageItem(message) {
        const item = document.createElement("div");
        item.className = `message-item ${message.type}`;

        const fromAgent = this.state.agents[message.from_agent_id];
        const toAgent = this.state.agents[message.to_agent_id];
        const timestamp = new Date(message.timestamp);

        item.innerHTML = `
            <div class="message-header">
                <div class="message-participants">
                    <span class="message-from">${
                        fromAgent ? fromAgent.name : "System"
                    }</span>
                    ${
                        toAgent
                            ? `<i class="fas fa-arrow-right"></i><span class="message-to">${toAgent.name}</span>`
                            : ""
                    }
                </div>
                <div class="message-meta">
                    <span class="message-type">${this.formatMessageType(
                        message.type
                    )}</span>
                    <span class="message-time">${timestamp.toLocaleTimeString()}</span>
                </div>
            </div>
            <div class="message-content">
                <p>${this.formatMessageContent(message.content)}</p>
            </div>
        `;

        return item;
    }

    updateTaskQueueDisplay() {
        const updateElement = (id, value) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        };

        updateElement("tasks-pending", this.state.taskQueue.pending);
        updateElement("tasks-in-progress", this.state.taskQueue.in_progress);
        updateElement("tasks-completed", this.state.taskQueue.completed);
        updateElement("tasks-failed", this.state.taskQueue.failed);

        // Update progress calculation
        const total = Object.values(this.state.taskQueue).reduce(
            (sum, count) => sum + count,
            0
        );
        if (total > 0) {
            const progress = (this.state.taskQueue.completed / total) * 100;
            this.updateProgressBar(progress);
        }
    }

    updateMetricsDisplay() {
        const metrics = this.state.metrics;
        if (!metrics) return;

        const updateElement = (id, value) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        };

        updateElement("active-agents-count", metrics.active_agents || 0);
        updateElement("tasks-completed", metrics.tasks_processed || 0);
        updateElement("messages-sent", metrics.messages_sent || 0);
        updateElement(
            "system-uptime",
            this.formatDuration(metrics.uptime || 0)
        );
        updateElement("files-created", metrics.files_created || 0);
        updateElement("api-calls", metrics.api_calls || 0);

        // Update header metrics
        updateElement("header-active-agents", metrics.active_agents || 0);
        updateElement("header-tasks-completed", metrics.tasks_processed || 0);
        updateElement(
            "header-system-uptime",
            this.formatDuration(metrics.uptime || 0)
        );
    }

    updateProjectStatus() {
        const statusElement = document.getElementById("project-status");
        if (!statusElement) return;

        const statusIndicator =
            statusElement.querySelector(".status-indicator");
        const statusText = statusIndicator.querySelector("span:last-child");
        const statusDot = statusIndicator.querySelector(".status-dot");

        if (this.state.systemRunning) {
            statusDot.className = "status-dot working";
            statusText.textContent = "Running";
        } else {
            statusDot.className = "status-dot idle";
            statusText.textContent = "Idle";
        }
    }

    updateProgressBar(percentage) {
        const progressBar = document.querySelector(".progress-bar");
        if (progressBar) {
            progressBar.style.width = `${percentage}%`;
        }
    }

    updateConnectionStatus(connected) {
        const statusElement = document.getElementById("connection-status");
        if (statusElement) {
            const dot = statusElement.querySelector(".status-dot");
            const text = statusElement.querySelector("span:last-child");

            if (connected) {
                dot.className = "status-dot connected";
                text.textContent = "Connected";
            } else {
                dot.className = "status-dot disconnected";
                text.textContent = "Disconnected";
            }
        }
    }

    updateProjectControls() {
        const startBtn = document.getElementById("start-project");
        const stopBtn = document.getElementById("stop-project");
        const pauseBtn = document.getElementById("pause-project");

        if (startBtn) startBtn.disabled = this.state.systemRunning;
        if (stopBtn) stopBtn.disabled = !this.state.systemRunning;
        if (pauseBtn) pauseBtn.disabled = !this.state.systemRunning;
    }

    // User Actions
    async startProject() {
        const description = document
            .getElementById("project-description")
            .value.trim();

        if (!description) {
            this.showNotification(
                "Please enter a project description",
                "warning"
            );
            return;
        }

        if (description.length < 10) {
            this.showNotification(
                "Project description must be at least 10 characters",
                "warning"
            );
            return;
        }

        this.showLoading("Starting project...");

        try {
            const response = await fetch("/api/project/start", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ description }),
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, "success");
                this.state.currentProject = data.project;
                this.state.systemRunning = true;
                this.updateProjectControls();
            } else {
                this.showNotification(
                    data.error || "Failed to start project",
                    "error"
                );
            }
        } catch (error) {
            console.error("Error starting project:", error);
            this.showNotification("Network error. Please try again.", "error");
        } finally {
            this.hideLoading();
        }
    }

    async stopProject() {
        if (!confirm("Are you sure you want to stop the project?")) {
            return;
        }

        try {
            const response = await fetch("/api/project/stop", {
                method: "POST",
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification(data.message, "info");
                this.state.systemRunning = false;
                this.updateProjectControls();
            } else {
                this.showNotification(
                    data.error || "Failed to stop project",
                    "error"
                );
            }
        } catch (error) {
            console.error("Error stopping project:", error);
            this.showNotification("Network error. Please try again.", "error");
        }
    }

    async downloadProject() {
        try {
            const response = await fetch("/api/project/download");

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `project_${
                    new Date().toISOString().split("T")[0]
                }.zip`;
                a.click();
                window.URL.revokeObjectURL(url);

                this.showNotification(
                    "Project downloaded successfully",
                    "success"
                );
            } else {
                const data = await response.json();
                this.showNotification(
                    data.error || "Failed to download project",
                    "error"
                );
            }
        } catch (error) {
            console.error("Error downloading project:", error);
            this.showNotification("Network error. Please try again.", "error");
        }
    }

    loadTemplate(templateName) {
        const templates = {
            "web-app":
                "Create a modern web application with React frontend and Flask backend. Include user authentication, responsive design, and a dashboard with real-time updates.",
            api: "Build a RESTful API with Flask, including user authentication, CRUD operations, input validation, error handling, and comprehensive API documentation.",
            dashboard:
                "Create an analytics dashboard with interactive charts, real-time data updates, user management, and export functionality using React and Chart.js.",
            mobile: "Build a cross-platform mobile application using React Native with navigation, state management, offline support, and push notifications.",
        };

        const description = templates[templateName];
        if (description) {
            document.getElementById("project-description").value = description;
            this.showNotification(`Template loaded: ${templateName}`, "info");
        }
    }

    refreshDashboard() {
        this.showLoading("Refreshing dashboard...");

        setTimeout(() => {
            this.loadInitialData();
            this.hideLoading();
            this.showNotification("Dashboard refreshed", "success");
        }, 1000);
    }

    switchView(viewName) {
        // Hide all views
        document.querySelectorAll(".view").forEach((view) => {
            view.classList.remove("active");
        });

        // Show target view
        const targetView = document.getElementById(`${viewName}-view`);
        if (targetView) {
            targetView.classList.add("active");
        }

        // Update active tab
        document.querySelectorAll(".nav-tab").forEach((tab) => {
            tab.classList.remove("active");
        });

        const activeTab = document.querySelector(`[data-view="${viewName}"]`);
        if (activeTab) {
            activeTab.classList.add("active");
        }

        this.state.currentView = viewName;

        // Load view-specific data
        switch (viewName) {
            case "performance":
                this.loadPerformanceData();
                break;
            case "files":
                this.loadProjectFiles();
                break;
            case "logs":
                this.loadSystemLogs();
                break;
        }
    }

    // Utility functions
    calculatePerformanceScore(agent) {
        const metrics = agent.performance_metrics || {};
        const baseScore = Math.min(metrics.tasks_completed * 10, 70);
        const qualityScore = metrics.quality_score || 85;

        return Math.min(baseScore + (qualityScore - 75), 100);
    }

    getRelativeTime(timestamp) {
        const now = new Date();
        const time = new Date(timestamp);
        const diff = now - time;

        if (diff < 60000) return "Just now";
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return `${Math.floor(diff / 86400000)}d ago`;
    }

    formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;

        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }

    formatStatus(status) {
        const statusMap = {
            idle: "Idle",
            working: "Working",
            completed: "Completed",
            error: "Error",
            reviewing: "Reviewing",
        };
        return statusMap[status] || status;
    }

    formatMessageType(type) {
        const typeMap = {
            task_assignment: "Task Assignment",
            task_completion: "Task Completed",
            status_update: "Status Update",
            communication: "Communication",
            error: "Error",
        };
        return typeMap[type] || type;
    }

    formatMessageContent(content) {
        // Truncate long messages
        if (content.length > 200) {
            return content.substring(0, 200) + "...";
        }
        return content;
    }

    getAgentName(agentId) {
        const agent = this.state.agents[agentId];
        return agent ? agent.name : "Unknown";
    }

    showNotification(message, type = "info", duration = 5000) {
        const notification = document.createElement("div");
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas fa-${this.getNotificationIcon(type)}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">
                <i class="fas fa-times"></i>
            </button>
        `;

        const container = document.getElementById("notification-container");
        container.appendChild(notification);

        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentElement) {
                    notification.remove();
                }
            }, duration);
        }
    }

    getNotificationIcon(type) {
        const icons = {
            success: "check-circle",
            error: "exclamation-triangle",
            warning: "exclamation-circle",
            info: "info-circle",
        };
        return icons[type] || "info-circle";
    }

    showLoading(message = "Loading...") {
        const overlay = document.getElementById("loading-overlay");
        if (overlay) {
            const text = overlay.querySelector("p");
            if (text) text.textContent = message;
            overlay.classList.add("active");
        }
    }

    hideLoading() {
        const overlay = document.getElementById("loading-overlay");
        if (overlay) {
            overlay.classList.remove("active");
        }
    }

    closeAllModals() {
        document.querySelectorAll(".modal").forEach((modal) => {
            modal.classList.remove("active");
        });
    }

    // Stub methods for features to be implemented
    pauseProject() {
        this.showNotification("Pause feature coming soon", "info");
    }

    showAgentDetails(agentId) {
        const agent = this.state.agents[agentId];
        if (agent) {
            console.log("Agent details:", agent);
            this.showNotification(`Agent details: ${agent.name}`, "info");
        }
    }

    toggleAgent(agentId) {
        const agent = this.state.agents[agentId];
        if (agent) {
            const action = agent.is_active ? "paused" : "resumed";
            this.showNotification(`Agent ${agent.name} ${action}`, "info");
        }
    }

    exportLogs() {
        this.showNotification("Export logs feature coming soon", "info");
    }

    showPerformanceReport() {
        this.showNotification("Performance report feature coming soon", "info");
    }

    loadPerformanceData() {
        console.log("Loading performance data...");
    }

    async loadProjectFiles() {
        try {
            const response = await fetch("/api/project/files/list");
            const data = await response.json();

            if (data.success) {
                this.updateFilesDisplay(data.files);
            } else {
                this.showNotification("Failed to load project files", "error");
            }
        } catch (error) {
            console.error("Error loading project files:", error);
            this.showNotification("Error loading project files", "error");
        }
    }

    updateFilesDisplay(files) {
        const filesContainer = document.getElementById("files-container");
        if (!filesContainer) return;

        if (files.length === 0) {
            filesContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-folder-open"></i>
                    <h3>No files created yet</h3>
                    <p>Files will appear here as the project progresses.</p>
                </div>
            `;
            return;
        }

        // Group files by type
        const filesByType = {};
        files.forEach((file) => {
            if (!filesByType[file.type]) {
                filesByType[file.type] = [];
            }
            filesByType[file.type].push(file);
        });

        let html = '<div class="files-grid">';

        Object.entries(filesByType).forEach(([type, typeFiles]) => {
            html += `
                <div class="file-type-section">
                    <h3 class="file-type-header">
                        <i class="fas fa-${this.getFileTypeIcon(type)}"></i>
                        ${this.getFileTypeName(type)} (${typeFiles.length})
                    </h3>
                    <div class="file-list">
            `;

            typeFiles.forEach((file) => {
                html += this.createFileItem(file);
            });

            html += "</div></div>";
        });

        html += "</div>";
        filesContainer.innerHTML = html;
    }

    createFileItem(file) {
        const size = this.formatFileSize(file.size);
        const icon = this.getFileTypeIcon(file.type);

        return `
            <div class="file-item" onclick="app.viewFile('${file.name}')">
                <div class="file-icon">
                    <i class="fas fa-${icon}"></i>
                </div>
                <div class="file-info">
                    <div class="file-name">${file.name}</div>
                    <div class="file-meta">
                        <span class="file-size">${size}</span>
                        <span class="file-lines">${file.lines} lines</span>
                    </div>
                </div>
                <div class="file-actions">
                    <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); app.downloadFile('${file.name}')">
                        <i class="fas fa-download"></i>
                    </button>
                </div>
            </div>
        `;
    }

    getFileTypeIcon(type) {
        const icons = {
            python: "code",
            javascript: "code",
            html: "file-code",
            css: "file-code",
            json: "file-code",
            yaml: "file-code",
            markdown: "file-alt",
            text: "file-alt",
            docker: "cube",
            shell: "terminal",
            other: "file",
        };
        return icons[type] || "file";
    }

    getFileTypeName(type) {
        const names = {
            python: "Python Files",
            javascript: "JavaScript Files",
            html: "HTML Files",
            css: "CSS Files",
            json: "JSON Files",
            yaml: "YAML Files",
            markdown: "Markdown Files",
            text: "Text Files",
            docker: "Docker Files",
            shell: "Shell Scripts",
            other: "Other Files",
        };
        return names[type] || "Other Files";
    }

    formatFileSize(bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    async viewFile(filename) {
        try {
            const response = await fetch(
                `/api/project/files/${encodeURIComponent(filename)}`
            );
            const data = await response.json();

            if (data.success) {
                this.showFileModal(data);
            } else {
                this.showNotification("Failed to load file content", "error");
            }
        } catch (error) {
            console.error("Error viewing file:", error);
            this.showNotification("Error viewing file", "error");
        }
    }

    showFileModal(fileData) {
        const modal = document.createElement("div");
        modal.className = "modal active";
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3>
                        <i class="fas fa-${this.getFileTypeIcon(
                            fileData.type
                        )}"></i>
                        ${fileData.filename}
                    </h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="file-stats">
                        <span class="stat">
                            <i class="fas fa-file"></i>
                            ${this.formatFileSize(fileData.size)}
                        </span>
                        <span class="stat">
                            <i class="fas fa-list"></i>
                            ${fileData.lines} lines
                        </span>
                        <span class="stat">
                            <i class="fas fa-code"></i>
                            ${fileData.type}
                        </span>
                    </div>
                    <div class="code-viewer">
                        <pre><code class="language-${this.getCodeLanguage(
                            fileData.type
                        )}">${this.escapeHtml(fileData.content)}</code></pre>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-primary" onclick="app.downloadFile('${
                        fileData.filename
                    }')">
                        <i class="fas fa-download"></i>
                        Download File
                    </button>
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">
                        Close
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Highlight syntax if available
        if (window.hljs) {
            modal.querySelectorAll("pre code").forEach((block) => {
                hljs.highlightElement(block);
            });
        }
    }

    getCodeLanguage(type) {
        const languages = {
            python: "python",
            javascript: "javascript",
            html: "html",
            css: "css",
            json: "json",
            yaml: "yaml",
            markdown: "markdown",
            text: "text",
            docker: "dockerfile",
            shell: "bash",
        };
        return languages[type] || "text";
    }

    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    async downloadFile(filename) {
        try {
            const response = await fetch(
                `/api/project/files/${encodeURIComponent(filename)}`
            );
            const data = await response.json();

            if (data.success) {
                const blob = new Blob([data.content], { type: "text/plain" });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = filename;
                a.click();
                window.URL.revokeObjectURL(url);

                this.showNotification(`Downloaded ${filename}`, "success");
            } else {
                this.showNotification("Failed to download file", "error");
            }
        } catch (error) {
            console.error("Error downloading file:", error);
            this.showNotification("Error downloading file", "error");
        }
    }

    loadSystemLogs() {
        console.log("Loading system logs...");
    }

    filterAgents(searchTerm, filterType) {
        console.log("Filtering agents:", searchTerm, filterType);
    }

    filterMessages(messageType) {
        console.log("Filtering messages:", messageType);
    }

    // Cleanup
    destroy() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
        }
        if (this.socket) {
            this.socket.disconnect();
        }
    }
}

// Initialize app
let app;

document.addEventListener("DOMContentLoaded", () => {
    app = new EnhancedMultiAgentApp();

    // Global app reference
    window.app = app;

    console.log("🚀 Enhanced Multi-Agent System initialized");
});

// Error handling
window.addEventListener("error", (e) => {
    console.error("Application error:", e.error);
    if (app) {
        app.hideLoading();
        app.showNotification(
            "An error occurred. Please check the console.",
            "error"
        );
    }
});

// Handle online/offline events
window.addEventListener("online", () => {
    if (app) {
        app.showNotification("Connection restored", "success");
    }
});

window.addEventListener("offline", () => {
    if (app) {
        app.showNotification("Connection lost", "warning");
    }
});

// Handle page visibility
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        console.log("Page hidden");
    } else {
        console.log("Page visible");
        if (app && app.connected) {
            app.refreshDashboard();
        }
    }
});
