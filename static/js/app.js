// Enhanced Multi-Agent System Frontend Application
class EnhancedMultiAgentApp {
    constructor() {
        this.agents = {};
        this.messages = [];
        this.systemRunning = false;
        this.currentProject = null;
        this.socket = null;
        this.taskQueue = {
            pending: 0,
            in_progress: 0,
            completed: 0,
            failed: 0,
        };
        this.performanceMetrics = {};
        this.realTimeUpdates = true;
        this.notificationQueue = [];
        this.codePreview = null;
        this.projectStructure = null;

        this.init();
    }

    init() {
        this.setupSocketIO();
        this.setupEventListeners();
        this.setupNavigation();
        this.setupNotifications();
        this.loadAgents();
        this.startMetricsPolling();
        this.setupKeyboardShortcuts();
        this.setupProgressTracking();
    }

    setupSocketIO() {
        this.socket = io();

        this.socket.on("connect", () => {
            console.log("✅ Connected to enhanced server");
            this.updateSystemStatus("Connected", "success");
            this.showNotification("Connected to enhanced system", "success");
        });

        this.socket.on("disconnect", () => {
            console.log("❌ Disconnected from server");
            this.updateSystemStatus("Disconnected", "error");
            this.showNotification("Connection lost", "error");
        });

        this.socket.on("agents_updated", (data) => {
            this.agents = data.agents;
            this.messages = data.messages || [];
            this.taskQueue = data.tasks || this.taskQueue;
            this.updateUI();
            this.updateTaskQueueDisplay();
        });

        this.socket.on("task_progress", (data) => {
            this.updateTaskProgress(data);
        });

        this.socket.on("code_generated", (data) => {
            this.handleCodeGeneration(data);
        });

        this.socket.on("project_completed", (data) => {
            this.handleProjectCompletion(data);
        });

        this.socket.on("agent_error", (data) => {
            this.handleAgentError(data);
        });
    }

    setupEventListeners() {
        // Enhanced project controls
        const startBtn = document.getElementById("start-project");
        if (startBtn) {
            startBtn.addEventListener("click", () => {
                this.startProject();
            });
        }

        const stopBtn = document.getElementById("stop-project");
        if (stopBtn) {
            stopBtn.addEventListener("click", () => {
                this.stopProject();
            });
        }

        const pauseBtn = document.getElementById("pause-project");
        if (pauseBtn) {
            pauseBtn.addEventListener("click", () => {
                this.pauseProject();
            });
        }

        // Enhanced agent management
        const addAgentBtn = document.getElementById("add-agent");
        if (addAgentBtn) {
            addAgentBtn.addEventListener("click", () => {
                this.showAddAgentModal();
            });
        }

        const bulkActionsBtn = document.getElementById("bulk-actions");
        if (bulkActionsBtn) {
            bulkActionsBtn.addEventListener("click", () => {
                this.showBulkActionsModal();
            });
        }

        // Real-time controls
        const toggleRealtimeBtn = document.getElementById("toggle-realtime");
        if (toggleRealtimeBtn) {
            toggleRealtimeBtn.addEventListener("click", () => {
                this.toggleRealTimeUpdates();
            });
        }

        const exportLogsBtn = document.getElementById("export-logs");
        if (exportLogsBtn) {
            exportLogsBtn.addEventListener("click", () => {
                this.exportLogs();
            });
        }

        // Performance monitoring
        const perfReportBtn = document.getElementById("performance-report");
        if (perfReportBtn) {
            perfReportBtn.addEventListener("click", () => {
                this.showPerformanceReport();
            });
        }

        // Code preview
        const previewCodeBtn = document.getElementById("preview-code");
        if (previewCodeBtn) {
            previewCodeBtn.addEventListener("click", () => {
                this.showCodePreview();
            });
        }

        // Modal controls
        document.querySelectorAll(".modal-close").forEach((btn) => {
            btn.addEventListener("click", () => {
                this.closeModal();
            });
        });
    }

    setupNavigation() {
        document.querySelectorAll(".nav-tab").forEach((tab) => {
            tab.addEventListener("click", (e) => {
                e.preventDefault();
                const viewName = tab.dataset.view;
                this.switchView(viewName);
                this.updateActiveTab(tab);
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
        const shortcuts = {
            "ctrl+enter": () => this.startProject(),
            "ctrl+space": () => this.pauseProject(),
            "ctrl+shift+c": () => this.showCodePreview(),
            "ctrl+shift+p": () => this.showPerformanceReport(),
            "ctrl+shift+a": () => this.showAddAgentModal(),
            escape: () => this.closeModal(),
        };

        document.addEventListener("keydown", (e) => {
            const key = [
                e.ctrlKey ? "ctrl" : "",
                e.shiftKey ? "shift" : "",
                e.altKey ? "alt" : "",
                e.key.toLowerCase(),
            ]
                .filter((k) => k)
                .join("+");

            if (shortcuts[key]) {
                e.preventDefault();
                shortcuts[key]();
            }
        });
    }

    setupProgressTracking() {
        // Create progress bar element
        const progressBar = document.createElement("div");
        progressBar.id = "project-progress";
        progressBar.className = "project-progress hidden";
        progressBar.innerHTML = `
            <div class="progress-bar">
                <div class="progress-fill" style="width: 0%"></div>
            </div>
            <div class="progress-text">Starting project...</div>
        `;
        document.querySelector(".header").appendChild(progressBar);
    }

    async loadAgents() {
        try {
            const response = await fetch("/api/agents");
            const data = await response.json();
            this.agents = data.agents;
            this.systemRunning = data.system_running;
            this.taskQueue = data.task_queue_status || this.taskQueue;
            this.updateUI();
            this.updateTaskQueueDisplay();
        } catch (error) {
            console.error("Failed to load agents:", error);
            this.showNotification("Failed to load agents", "error");
        }
    }

    updateUI() {
        this.updateAgentsView();
        this.updateMessagesView();
        this.updateSystemMetrics();
        this.updateProjectStatus();
    }

    updateAgentsView() {
        const grid = document.getElementById("agents-grid");
        if (!grid) return;

        grid.innerHTML = "";

        Object.values(this.agents).forEach((agent) => {
            const card = this.createEnhancedAgentCard(agent);
            grid.appendChild(card);
        });

        this.updateAgentSelectors();
    }

    createEnhancedAgentCard(agent) {
        const card = document.createElement("div");
        card.className = `agent-card ${agent.status} ${
            agent.is_active ? "active" : "inactive"
        }`;
        card.dataset.agentId = agent.id;

        const statusText = {
            idle: "Ready",
            working: "Working",
            completed: "Completed",
            error: "Error",
            reviewing: "Reviewing",
        };

        const performanceScore = this.calculatePerformanceScore(agent);
        const lastActivity = this.getRelativeTime(agent.last_activity);

        card.innerHTML = `
            <div class="agent-card-header">
                <div class="agent-info">
                    <h3 class="agent-card-title">${agent.name}</h3>
                    <span class="agent-card-type ${agent.type}">${
            agent.type
        }</span>
                </div>
                <div class="agent-status-indicator">
                    <span class="status-dot ${agent.status}"></span>
                    <span class="status-text">${
                        statusText[agent.status] || "Unknown"
                    }</span>
                </div>
            </div>
            <div class="agent-card-content">
                <div class="agent-card-role">${agent.role}</div>
                <div class="agent-card-specialty">${agent.specialty}</div>
                
                <div class="agent-metrics">
                    <div class="metric">
                        <span class="metric-label">Tasks Completed</span>
                        <span class="metric-value">${
                            agent.performance_metrics?.tasks_completed || 0
                        }</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Performance Score</span>
                        <span class="metric-value">${performanceScore}%</span>
                    </div>
                    <div class="metric">
                        <span class="metric-label">Last Activity</span>
                        <span class="metric-value">${lastActivity}</span>
                    </div>
                </div>

                <div class="agent-skills">
                    ${(agent.skills || [])
                        .map(
                            (skill) => `<span class="skill-tag">${skill}</span>`
                        )
                        .join("")}
                </div>

                <div class="agent-card-actions">
                    <button class="btn btn-outline btn-sm" onclick="app.showAgentDetails('${
                        agent.id
                    }')">
                        <i class="fas fa-eye"></i> Details
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="app.assignTaskToAgent('${
                        agent.id
                    }')">
                        <i class="fas fa-tasks"></i> Assign Task
                    </button>
                    <button class="btn btn-outline btn-sm" onclick="app.toggleAgentStatus('${
                        agent.id
                    }')">
                        <i class="fas fa-power-off"></i> ${
                            agent.is_active ? "Pause" : "Resume"
                        }
                    </button>
                </div>
            </div>
        `;

        return card;
    }

    updateMessagesView() {
        const messagesList = document.getElementById("messages-list");
        if (!messagesList) return;

        messagesList.innerHTML = "";

        this.messages.slice(-50).forEach((message, index) => {
            const messageItem = this.createEnhancedMessageItem(message, index);
            messagesList.appendChild(messageItem);
        });

        messagesList.scrollTop = messagesList.scrollHeight;
    }

    createEnhancedMessageItem(message, index) {
        const item = document.createElement("div");
        item.className = `message-item ${message.type}`;
        item.dataset.messageId = index;

        const fromAgent = this.agents[message.from_agent_id];
        const toAgent = this.agents[message.to_agent_id];
        const timestamp = new Date(message.timestamp);

        item.innerHTML = `
            <div class="message-header">
                <div class="message-participants">
                    <span class="message-from">${
                        fromAgent ? fromAgent.name : "System"
                    }</span>
                    <i class="fas fa-arrow-right"></i>
                    <span class="message-to">${
                        toAgent ? toAgent.name : "System"
                    }</span>
                </div>
                <div class="message-meta">
                    <span class="message-type">${message.type}</span>
                    <span class="message-timestamp">${timestamp.toLocaleTimeString()}</span>
                </div>
            </div>
            <div class="message-content">
                <div class="message-text">${this.formatMessageContent(
                    message.content
                )}</div>
                ${
                    message.type === "code_update"
                        ? this.createCodePreview(message.content)
                        : ""
                }
            </div>
            <div class="message-actions">
                <button class="btn-icon" onclick="app.copyMessage(${index})">
                    <i class="fas fa-copy"></i>
                </button>
                <button class="btn-icon" onclick="app.bookmarkMessage(${index})">
                    <i class="fas fa-bookmark"></i>
                </button>
            </div>
        `;

        return item;
    }

    updateTaskQueueDisplay() {
        const updateElement = (id, value) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        };

        updateElement("tasks-pending", this.taskQueue.pending);
        updateElement("tasks-in-progress", this.taskQueue.in_progress);
        updateElement("tasks-completed", this.taskQueue.completed);
        updateElement("tasks-failed", this.taskQueue.failed);

        // Update progress bar
        const total =
            this.taskQueue.pending +
            this.taskQueue.in_progress +
            this.taskQueue.completed +
            this.taskQueue.failed;
        if (total > 0) {
            const progress = (this.taskQueue.completed / total) * 100;
            this.updateProgressBar(progress);
        }
    }

    updateProgressBar(percentage) {
        const progressBar = document.querySelector("#project-progress");
        const progressFill = document.querySelector(".progress-fill");
        const progressText = document.querySelector(".progress-text");

        if (progressBar && progressFill && progressText) {
            progressBar.classList.remove("hidden");
            progressFill.style.width = `${percentage}%`;
            progressText.textContent = `Project Progress: ${Math.round(
                percentage
            )}%`;
        }
    }

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

            if (response.ok) {
                this.currentProject = data.project;
                this.systemRunning = true;
                this.updateSystemStatus("Starting...", "working");
                this.showNotification(
                    "Project started successfully",
                    "success"
                );
                this.updateProjectControls(true);
                this.startProjectMonitoring();
            } else {
                this.showNotification(
                    data.error || "Failed to start project",
                    "error"
                );
            }
        } catch (error) {
            console.error("Failed to start project:", error);
            this.showNotification("Failed to start project", "error");
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

            if (response.ok) {
                this.systemRunning = false;
                this.updateSystemStatus("Stopped", "idle");
                this.showNotification("Project stopped", "info");
                this.updateProjectControls(false);
                this.stopProjectMonitoring();
            }
        } catch (error) {
            console.error("Failed to stop project:", error);
            this.showNotification("Failed to stop project", "error");
        }
    }

    async pauseProject() {
        try {
            const response = await fetch("/api/project/pause", {
                method: "POST",
            });

            if (response.ok) {
                this.showNotification("Project paused", "info");
                this.updateSystemStatus("Paused", "warning");
            }
        } catch (error) {
            console.error("Failed to pause project:", error);
            this.showNotification("Failed to pause project", "error");
        }
    }

    updateProjectControls(running) {
        const startBtn = document.getElementById("start-project");
        const stopBtn = document.getElementById("stop-project");
        const pauseBtn = document.getElementById("pause-project");

        if (startBtn) startBtn.disabled = running;
        if (stopBtn) stopBtn.disabled = !running;
        if (pauseBtn) pauseBtn.disabled = !running;
    }

    startProjectMonitoring() {
        this.projectMonitoringInterval = setInterval(() => {
            this.checkProjectStatus();
        }, 5000);
    }

    stopProjectMonitoring() {
        if (this.projectMonitoringInterval) {
            clearInterval(this.projectMonitoringInterval);
            this.projectMonitoringInterval = null;
        }
    }

    async checkProjectStatus() {
        try {
            const response = await fetch("/api/project/status");
            const data = await response.json();

            if (data.completed) {
                this.handleProjectCompletion(data);
            }
        } catch (error) {
            console.error("Failed to check project status:", error);
        }
    }

    handleProjectCompletion(data) {
        this.showNotification("🎉 Project completed successfully!", "success");
        this.updateSystemStatus("Completed", "success");
        this.updateProgressBar(100);
        this.stopProjectMonitoring();

        // Auto-download project files
        if (data.auto_download) {
            setTimeout(() => {
                window.location.href = "/api/project/download";
            }, 2000);
        }
    }

    async showPerformanceReport() {
        try {
            const response = await fetch("/api/performance");
            const data = await response.json();

            const modal = document.getElementById("performance-modal");
            const content = document.getElementById("performance-content");

            content.innerHTML = `
                <div class="performance-report">
                    <div class="performance-section">
                        <h4>System Performance</h4>
                        <div class="metrics-grid">
                            <div class="metric-card">
                                <div class="metric-title">Uptime</div>
                                <div class="metric-value">${this.formatDuration(
                                    data.uptime
                                )}</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-title">API Calls</div>
                                <div class="metric-value">${
                                    data.metrics.api_calls
                                }</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-title">Cache Hit Rate</div>
                                <div class="metric-value">${(
                                    data.cache_hit_rate * 100
                                ).toFixed(1)}%</div>
                            </div>
                            <div class="metric-card">
                                <div class="metric-title">Error Rate</div>
                                <div class="metric-value">${(
                                    data.error_rate * 100
                                ).toFixed(1)}%</div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="performance-section">
                        <h4>Response Times</h4>
                        <div class="chart-container">
                            <div class="metric-bar">
                                <span>Avg Response Time</span>
                                <div class="bar">
                                    <div class="bar-fill" style="width: ${Math.min(
                                        (data.metrics.avg_response_time / 5) *
                                            100,
                                        100
                                    )}%"></div>
                                </div>
                                <span>${data.metrics.avg_response_time.toFixed(
                                    2
                                )}s</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="performance-section">
                        <h4>Agent Performance</h4>
                        <div class="agent-performance-list">
                            ${Object.values(this.agents)
                                .map(
                                    (agent) => `
                                <div class="agent-performance-item">
                                    <span class="agent-name">${
                                        agent.name
                                    }</span>
                                    <span class="agent-tasks">${
                                        agent.performance_metrics
                                            ?.tasks_completed || 0
                                    } tasks</span>
                                    <span class="agent-score">${this.calculatePerformanceScore(
                                        agent
                                    )}%</span>
                                </div>
                            `
                                )
                                .join("")}
                        </div>
                    </div>
                </div>
            `;

            modal.classList.add("active");
        } catch (error) {
            console.error("Failed to load performance report:", error);
            this.showNotification("Failed to load performance report", "error");
        }
    }

    async showCodePreview() {
        try {
            const response = await fetch("/api/project/files");
            const data = await response.json();

            const modal = document.getElementById("code-preview-modal");
            const content = document.getElementById("code-preview-content");

            content.innerHTML = `
                <div class="code-preview">
                    <div class="file-explorer">
                        <h4>Project Files</h4>
                        <div class="file-tree">
                            ${this.renderFileTree(data.tree)}
                        </div>
                    </div>
                    <div class="code-editor">
                        <div class="editor-header">
                            <span id="current-file">Select a file to preview</span>
                        </div>
                        <div class="editor-content">
                            <pre id="code-content">Select a file from the tree to view its contents</pre>
                        </div>
                    </div>
                </div>
            `;

            modal.classList.add("active");
        } catch (error) {
            console.error("Failed to load code preview:", error);
            this.showNotification("Failed to load code preview", "error");
        }
    }

    renderFileTree(tree, path = "") {
        return tree
            .map((item) => {
                if (item.type === "folder") {
                    return `
                    <div class="file-item folder" data-path="${path}${item.name}">
                        <i class="fas fa-folder"></i>
                        <span>${item.name}</span>
                    </div>
                `;
                } else {
                    return `
                    <div class="file-item file" data-path="${path}${
                        item.name
                    }" onclick="app.previewFile('${path}${item.name}')">
                        <i class="fas fa-file-code"></i>
                        <span>${item.name}</span>
                        <small class="file-size">${this.formatFileSize(
                            item.size
                        )}</small>
                    </div>
                `;
                }
            })
            .join("");
    }

    async previewFile(filePath) {
        try {
            const response = await fetch(
                `/api/project/file?path=${encodeURIComponent(filePath)}`
            );
            const data = await response.json();

            document.getElementById("current-file").textContent = filePath;
            document.getElementById("code-content").textContent = data.content;

            // Apply syntax highlighting if possible
            if (window.hljs) {
                hljs.highlightAll();
            }
        } catch (error) {
            console.error("Failed to preview file:", error);
            this.showNotification("Failed to preview file", "error");
        }
    }

    startMetricsPolling() {
        this.updateMetrics();
        this.metricsInterval = setInterval(() => {
            this.updateMetrics();
        }, 2000);
    }

    async updateMetrics() {
        try {
            const response = await fetch("/api/metrics");
            const data = await response.json();

            this.updateElement("active-agents-count", data.active_agents);
            this.updateElement("tasks-completed", data.tasks_completed);
            this.updateElement("messages-sent", data.messages_sent);
            this.updateElement(
                "system-uptime",
                this.formatDuration(data.system_uptime)
            );
            this.updateElement("files-created", data.files_created);

            // Update task queue metrics
            this.taskQueue = {
                pending: data.tasks_pending,
                in_progress: data.tasks_in_progress,
                completed: data.tasks_completed,
                failed: data.tasks_failed,
            };

            this.updateTaskQueueDisplay();
        } catch (error) {
            // Silently handle metrics errors
        }
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

        // Auto-remove notification
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, duration);
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

    // Utility methods
    calculatePerformanceScore(agent) {
        const metrics = agent.performance_metrics || {};
        const tasksCompleted = metrics.tasks_completed || 0;
        const baseScore = Math.min(tasksCompleted * 10, 70);
        const qualityScore = metrics.code_quality_score || 0;
        const collaborationScore = metrics.collaboration_score || 0;

        return Math.min(baseScore + qualityScore + collaborationScore, 100);
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
            return `${hours}h ${minutes}m ${secs}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }

    formatFileSize(bytes) {
        if (bytes === 0) return "0 B";

        const k = 1024;
        const sizes = ["B", "KB", "MB", "GB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));

        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
    }

    formatMessageContent(content) {
        // Format code blocks
        content = content.replace(
            /```(\w+)?\n([\s\S]*?)```/g,
            (match, lang, code) => {
                return `<pre class="code-block ${lang || ""}">${this.escapeHtml(
                    code
                )}</pre>`;
            }
        );

        // Format inline code
        content = content.replace(/`([^`]+)`/g, "<code>$1</code>");

        // Format URLs
        content = content.replace(
            /(https?:\/\/[^\s]+)/g,
            '<a href="$1" target="_blank">$1</a>'
        );

        return content;
    }

    escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    }

    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = value;
        }
    }

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    switchView(viewName) {
        document.querySelectorAll(".view").forEach((view) => {
            view.classList.remove("active");
            view.style.display = "none";
        });

        const activeView = document.getElementById(`${viewName}-view`);
        if (activeView) {
            activeView.classList.add("active");
            activeView.style.display = "";
        }

        // Load view-specific data
        switch (viewName) {
            case "communications":
                this.loadDetailedLog();
                break;
            case "files":
                this.loadFileTree();
                break;
            case "performance":
                this.showPerformanceReport();
                break;
        }
    }

    updateActiveTab(activeTab) {
        document.querySelectorAll(".nav-tab").forEach((tab) => {
            tab.classList.remove("active");
        });
        activeTab.classList.add("active");
    }

    showLoading(message = "Loading...") {
        const overlay = document.getElementById("loading-overlay");
        const text = overlay.querySelector("p");
        if (text) text.textContent = message;
        overlay.classList.add("active");
    }

    hideLoading() {
        document.getElementById("loading-overlay").classList.remove("active");
    }

    closeModal() {
        document.querySelectorAll(".modal").forEach((modal) => {
            modal.classList.remove("active");
        });
    }

    updateSystemStatus(status, type) {
        const statusBtn = document.getElementById("system-status");
        if (!statusBtn) return;

        const icons = {
            success: "fas fa-check-circle",
            working: "fas fa-spinner fa-spin",
            error: "fas fa-exclamation-triangle",
            idle: "fas fa-pause-circle",
            warning: "fas fa-exclamation-circle",
        };

        const colors = {
            success: "btn-success",
            working: "btn-warning",
            error: "btn-danger",
            idle: "btn-secondary",
            warning: "btn-warning",
        };

        statusBtn.className = `btn ${colors[type] || "btn-secondary"}`;
        statusBtn.innerHTML = `<i class="${
            icons[type] || "fas fa-question-circle"
        }"></i> ${status}`;
    }

    // Export functionality
    async exportLogs() {
        try {
            const response = await fetch("/api/log");
            const data = await response.json();

            const blob = new Blob([JSON.stringify(data, null, 2)], {
                type: "application/json",
            });

            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `system-logs-${
                new Date().toISOString().split("T")[0]
            }.json`;
            a.click();
            URL.revokeObjectURL(url);

            this.showNotification("Logs exported successfully", "success");
        } catch (error) {
            console.error("Failed to export logs:", error);
            this.showNotification("Failed to export logs", "error");
        }
    }

    // Placeholder methods for enhanced features
    async loadDetailedLog() {
        // Implementation similar to original but with enhanced formatting
        const logDiv = document.getElementById("detailed-log");
        if (!logDiv) return;

        logDiv.innerHTML =
            '<div class="log-loading">Loading enhanced log...</div>';

        try {
            const response = await fetch("/api/log");
            const data = await response.json();

            logDiv.innerHTML = "";

            data.log.forEach((entry) => {
                const line = document.createElement("div");
                line.className = `log-entry ${entry.event}`;
                line.innerHTML = `
                    <span class="log-timestamp">[${new Date(
                        entry.timestamp
                    ).toLocaleTimeString()}]</span>
                    <span class="log-event">${entry.event}</span>
                    <span class="log-description">${entry.description}</span>
                `;
                logDiv.appendChild(line);
            });

            logDiv.scrollTop = logDiv.scrollHeight;
        } catch (error) {
            logDiv.innerHTML =
                '<div class="log-error">Error loading log.</div>';
        }
    }

    async loadFileTree() {
        const container = document.getElementById("file-tree-container");
        if (!container) return;

        container.innerHTML = '<div class="loading">Loading file tree...</div>';

        try {
            const response = await fetch("/api/project/files");
            const data = await response.json();

            container.innerHTML = this.renderFileTree(data.tree);
        } catch (error) {
            container.innerHTML =
                '<div class="error">Error loading file tree.</div>';
        }
    }

    // Additional methods for enhanced functionality
    toggleRealTimeUpdates() {
        this.realTimeUpdates = !this.realTimeUpdates;
        const btn = document.getElementById("toggle-realtime");
        if (btn) {
            btn.textContent = this.realTimeUpdates
                ? "Disable Real-time"
                : "Enable Real-time";
        }
        this.showNotification(
            `Real-time updates ${
                this.realTimeUpdates ? "enabled" : "disabled"
            }`,
            "info"
        );
    }

    async assignTaskToAgent(agentId) {
        const task = prompt("Enter task description:");
        if (!task) return;

        try {
            const response = await fetch(`/api/agents/${agentId}/assign_task`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ task }),
            });

            if (response.ok) {
                this.showNotification("Task assigned successfully", "success");
            } else {
                this.showNotification("Failed to assign task", "error");
            }
        } catch (error) {
            console.error("Failed to assign task:", error);
            this.showNotification("Failed to assign task", "error");
        }
    }

    async toggleAgentStatus(agentId) {
        const agent = this.agents[agentId];
        if (!agent) return;

        const action = agent.is_active ? "deactivate" : "activate";

        try {
            const response = await fetch(`/api/agents/${agentId}/${action}`, {
                method: "POST",
            });

            if (response.ok) {
                this.showNotification(
                    `Agent ${action}d successfully`,
                    "success"
                );
                this.loadAgents(); // Refresh agent data
            } else {
                this.showNotification(`Failed to ${action} agent`, "error");
            }
        } catch (error) {
            console.error(`Failed to ${action} agent:`, error);
            this.showNotification(`Failed to ${action} agent`, "error");
        }
    }

    showAgentDetails(agentId) {
        const agent = this.agents[agentId];
        if (!agent) return;

        const modal = document.getElementById("agent-details-modal");
        const title = document.getElementById("agent-details-title");
        const content = document.getElementById("agent-details-content");

        title.innerHTML = `<i class="fas fa-user"></i> ${agent.name}`;

        content.innerHTML = `
            <div class="agent-details-enhanced">
                <div class="details-grid">
                    <div class="detail-section">
                        <h4><i class="fas fa-user-tag"></i> Basic Information</h4>
                        <div class="detail-items">
                            <div class="detail-item">
                                <span class="detail-label">Name:</span>
                                <span class="detail-value">${agent.name}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Role:</span>
                                <span class="detail-value">${agent.role}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Type:</span>
                                <span class="detail-value">${agent.type}</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Status:</span>
                                <span class="detail-value status-${
                                    agent.status
                                }">${agent.status}</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="detail-section">
                        <h4><i class="fas fa-chart-line"></i> Performance</h4>
                        <div class="performance-meters">
                            <div class="meter">
                                <span class="meter-label">Overall Score</span>
                                <div class="meter-bar">
                                    <div class="meter-fill" style="width: ${this.calculatePerformanceScore(
                                        agent
                                    )}%"></div>
                                </div>
                                <span class="meter-value">${this.calculatePerformanceScore(
                                    agent
                                )}%</span>
                            </div>
                            <div class="meter">
                                <span class="meter-label">Tasks Completed</span>
                                <div class="meter-bar">
                                    <div class="meter-fill" style="width: ${Math.min(
                                        (agent.performance_metrics
                                            ?.tasks_completed || 0) * 10,
                                        100
                                    )}%"></div>
                                </div>
                                <span class="meter-value">${
                                    agent.performance_metrics
                                        ?.tasks_completed || 0
                                }</span>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="detail-section full-width">
                    <h4><i class="fas fa-brain"></i> Specialty & Skills</h4>
                    <p class="specialty-text">${agent.specialty}</p>
                    <div class="skills-list">
                        ${(agent.skills || [])
                            .map(
                                (skill) =>
                                    `<span class="skill-tag">${skill}</span>`
                            )
                            .join("")}
                    </div>
                </div>
                
                <div class="detail-section full-width">
                    <h4><i class="fas fa-code"></i> Recent Work Output</h4>
                    <div class="work-output-container">
                        <pre class="work-output">${
                            agent.work_output || "No output yet"
                        }</pre>
                    </div>
                </div>
            </div>
        `;

        modal.classList.add("active");
    }
}

// Initialize the enhanced app
let app;

document.addEventListener("DOMContentLoaded", () => {
    app = new EnhancedMultiAgentApp();

    // Global helper functions
    window.createAgent = () => app.createAgent();
    window.closeModal = () => app.closeModal();
    window.app = app;

    console.log("🚀 Enhanced Multi-Agent System initialized");
});

// Enhanced error handling
window.addEventListener("error", (e) => {
    console.error("Application error:", e.error);
    if (app) {
        app.hideLoading();
        app.showNotification(
            "An error occurred. Check console for details.",
            "error"
        );
    }
});

// Enhanced offline/online handling
window.addEventListener("online", () => {
    if (app) {
        app.showNotification("Connection restored", "success");
        app.socket.connect();
    }
});

window.addEventListener("offline", () => {
    if (app) {
        app.showNotification("Connection lost", "warning");
        app.updateSystemStatus("Offline", "error");
    }
});
