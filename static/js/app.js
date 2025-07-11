// Multi-Agent System Frontend Application
class MultiAgentApp {
    constructor() {
        this.agents = {};
        this.messages = [];
        this.systemRunning = false;
        this.showConnections = true;
        this.currentAgent = null;
        this.socket = null;
        this.draggedAgent = null;
        this.dragOffset = { x: 0, y: 0 };

        this.init();
    }

    init() {
        this.setupSocketIO();
        this.setupEventListeners();
        this.setupNavigation();
        this.loadAgents();
        this.pollMetrics();
    }

    setupSocketIO() {
        this.socket = io();

        this.socket.on("connect", () => {
            console.log("Connected to server");
            this.updateSystemStatus("Connected", "success");
        });

        this.socket.on("disconnect", () => {
            console.log("Disconnected from server");
            this.updateSystemStatus("Disconnected", "error");
        });

        this.socket.on("agents_updated", (data) => {
            this.agents = data.agents;
            this.messages = data.messages || [];
            this.updateUI();
        });

        this.socket.on("agent_added", (agent) => {
            this.agents[agent.id] = agent;
            this.updateUI();
        });

        this.socket.on("agent_removed", (data) => {
            delete this.agents[data.agent_id];
            this.updateUI();
        });

        this.socket.on("message_sent", (message) => {
            this.messages.push(message);
            this.updateMessagesView();
        });

        this.socket.on("project_started", (data) => {
            this.systemRunning = true;
            this.agents = data.agents;
            this.updateSystemStatus("Running", "working");
            this.updateUI();
        });

        this.socket.on("project_stopped", () => {
            this.systemRunning = false;
            this.updateSystemStatus("Stopped", "idle");
            this.updateUI();
        });
    }

    setupEventListeners() {
        // Project controls
        document
            .getElementById("start-project")
            .addEventListener("click", () => {
                this.startProject();
            });

        document
            .getElementById("stop-project")
            .addEventListener("click", () => {
                this.stopProject();
            });

        // Agent management
        document.getElementById("add-agent").addEventListener("click", () => {
            this.showAddAgentModal();
        });

        document
            .getElementById("add-agent-btn")
            .addEventListener("click", () => {
                this.showAddAgentModal();
            });

        // Toggle connections
        document
            .getElementById("toggle-connections")
            .addEventListener("click", () => {
                this.toggleConnections();
            });

        // Message controls
        document
            .getElementById("send-message")
            .addEventListener("click", () => {
                this.sendMessage();
            });

        document
            .getElementById("clear-messages")
            .addEventListener("click", () => {
                this.clearMessages();
            });

        // Manual Task Assignment controls
        const manualTaskBtn = document.getElementById("manual-task-btn");
        if (manualTaskBtn) {
            manualTaskBtn.addEventListener("click", () => {
                this.openManualTaskModal();
            });
        }
        const assignTaskConfirm = document.getElementById(
            "assign-task-confirm"
        );
        if (assignTaskConfirm) {
            assignTaskConfirm.addEventListener("click", () => {
                this.assignManualTask();
            });
        }

        // Modal controls
        document.querySelectorAll(".modal-close").forEach((btn) => {
            btn.addEventListener("click", () => {
                this.closeModal();
            });
        });

        // Form submissions
        document.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                const target = e.target;
                if (target.id === "message-content") {
                    this.sendMessage();
                } else if (target.id === "project-description") {
                    this.startProject();
                }
            }
        });

        // Download project button
        const downloadBtn = document.getElementById("download-project");
        if (downloadBtn) {
            downloadBtn.addEventListener("click", () => {
                window.location = "/api/project/download";
            });
        }
    }

    setupNavigation() {
        document.querySelectorAll(".nav-tab").forEach((tab) => {
            tab.addEventListener("click", (e) => {
                // Remove active from all tabs
                document
                    .querySelectorAll(".nav-tab")
                    .forEach((t) => t.classList.remove("active"));
                // Add active to clicked tab
                tab.classList.add("active");
                // Get view name
                const viewName = tab.dataset.view;
                this.switchView(viewName);
                if (viewName === "files") {
                    this.loadFileTree();
                }
            });
        });
    }

    async loadAgents() {
        try {
            const response = await fetch("/api/agents");
            const data = await response.json();
            this.agents = data.agents;
            this.systemRunning = data.system_running;
            this.updateUI();
        } catch (error) {
            console.error("Failed to load agents:", error);
        }
    }

    updateUI() {
        this.updateAgentsView();
        this.updateMessagesView();
    }

    updateAgentsView() {
        const grid = document.getElementById("agents-grid");
        grid.innerHTML = "";

        Object.values(this.agents).forEach((agent) => {
            const card = this.createAgentCard(agent);
            grid.appendChild(card);
        });

        this.updateAgentSelectors();
    }

    createAgentCard(agent) {
        const card = document.createElement("div");
        card.className = "agent-card";

        const statusText = {
            idle: "Ready",
            working: "Working",
            completed: "Completed",
            error: "Error",
        };

        card.innerHTML = `
            <div class="agent-card-header">
                <h3 class="agent-card-title">${agent.name}</h3>
                <span class="agent-card-type ${agent.type}">${agent.type}</span>
            </div>
            <div class="agent-card-role">${agent.role}</div>
            <div class="agent-card-specialty">${agent.specialty}</div>
            <div class="agent-card-status">
                <span class="status-dot ${agent.status}"></span>
                <span>${statusText[agent.status] || "Unknown"}</span>
            </div>
            <div class="agent-card-actions">
                <button class="btn btn-outline" onclick="app.showAgentDetails('${
                    agent.id
                }')">
                    <i class="fas fa-eye"></i> View Details
                </button>
                <button class="btn btn-danger" onclick="app.deleteAgent('${
                    agent.id
                }')">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </div>
        `;

        return card;
    }

    updateMessagesView() {
        const messagesList = document.getElementById("messages-list");
        messagesList.innerHTML = "";

        this.messages.slice(-50).forEach((message) => {
            const messageItem = this.createMessageItem(message);
            messagesList.appendChild(messageItem);
        });

        messagesList.scrollTop = messagesList.scrollHeight;
    }

    createMessageItem(message) {
        const item = document.createElement("div");
        item.className = "message-item";

        const fromAgent = this.agents[message.from_agent_id];
        const toAgent = this.agents[message.to_agent_id];

        item.innerHTML = `
            <div class="message-header">
                <span class="message-from">${
                    fromAgent ? fromAgent.name : "Unknown"
                }</span>
                <span class="message-to">→ ${
                    toAgent ? toAgent.name : "Unknown"
                }</span>
                <span class="message-timestamp">${new Date(
                    message.timestamp
                ).toLocaleTimeString()}</span>
            </div>
            <div class="message-content">${message.content}</div>
        `;

        return item;
    }

    updateAgentSelectors() {
        // Only update the 'to' selector for user messages
        const toSelect = document.getElementById("message-to");
        if (toSelect) {
            const currentValue = toSelect.value;
            toSelect.innerHTML =
                '<option value="">Select recipient...</option>';
            Object.values(this.agents).forEach((agent) => {
                const option = document.createElement("option");
                option.value = agent.id;
                option.textContent = agent.name;
                toSelect.appendChild(option);
            });
            toSelect.value = currentValue;
        }
        // Also update manual task modal agent selector if present
        const manualSelect = document.getElementById("manual-task-agent");
        if (manualSelect) {
            const currentValue = manualSelect.value;
            manualSelect.innerHTML = "";
            Object.values(this.agents).forEach((agent) => {
                const option = document.createElement("option");
                option.value = agent.id;
                option.textContent = `${agent.name} (${agent.role})`;
                manualSelect.appendChild(option);
            });
            manualSelect.value = currentValue;
        }
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
        if (viewName === "communications") {
            this.loadDetailedLog();
        }
    }

    async startProject() {
        const description = document
            .getElementById("project-description")
            .value.trim();
        if (!description) {
            alert("Please enter a project description");
            return;
        }

        try {
            const response = await fetch("/api/project/start", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ description }),
            });

            if (response.ok) {
                document.getElementById("start-project").disabled = true;
                document.getElementById("stop-project").disabled = false;
                this.updateSystemStatus("Starting...", "working");
            }
        } catch (error) {
            console.error("Failed to start project:", error);
            alert("Failed to start project");
        }
    }

    async stopProject() {
        try {
            const response = await fetch("/api/project/stop", {
                method: "POST",
            });

            if (response.ok) {
                document.getElementById("start-project").disabled = false;
                document.getElementById("stop-project").disabled = true;
                this.updateSystemStatus("Stopped", "idle");
            }
        } catch (error) {
            console.error("Failed to stop project:", error);
            alert("Failed to stop project");
        }
    }

    showAddAgentModal() {
        document.getElementById("add-agent-modal").classList.add("active");
        this.updateAgentSelectors();
    }

    closeModal() {
        document.querySelectorAll(".modal").forEach((modal) => {
            modal.classList.remove("active");
        });
        this.currentAgent = null;
    }

    async createAgent() {
        const name = document.getElementById("agent-name").value.trim();
        const role = document.getElementById("agent-role").value.trim();
        const type = document.getElementById("agent-type").value;
        const specialty = document
            .getElementById("agent-specialty")
            .value.trim();
        const managerId = document.getElementById("agent-manager").value;

        if (!name || !role || !specialty) {
            alert("Please fill in all required fields");
            return;
        }

        try {
            const response = await fetch("/api/agents", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    name,
                    role,
                    type,
                    specialty,
                    manager_id: managerId || null,
                }),
            });

            if (response.ok) {
                this.closeModal();
                this.clearForm();
                this.loadAgents();
            }
        } catch (error) {
            console.error("Failed to create agent:", error);
            alert("Failed to create agent");
        }
    }

    async deleteAgent(agentId) {
        if (!confirm("Are you sure you want to delete this agent?")) {
            return;
        }

        try {
            const response = await fetch(`/api/agents/${agentId}`, {
                method: "DELETE",
            });

            if (response.ok) {
                this.closeModal();
                this.loadAgents();
            }
        } catch (error) {
            console.error("Failed to delete agent:", error);
            alert("Failed to delete agent");
        }
    }

    async updateAgentPosition(agentId, position) {
        try {
            await fetch(`/api/agents/${agentId}/position`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ position }),
            });
        } catch (error) {
            console.error("Failed to update agent position:", error);
        }
    }

    showAgentDetails(agentId) {
        const agent = this.agents[agentId];
        if (!agent) return;

        this.currentAgent = agent;
        const modal = document.getElementById("agent-details-modal");
        const title = document.getElementById("agent-details-title");
        const content = document.getElementById("agent-details-content");

        title.innerHTML = `<i class="fas fa-user"></i> ${agent.name}`;

        const subordinatesList = agent.subordinates
            ? agent.subordinates
                  .map((id) => this.agents[id]?.name || "Unknown")
                  .join(", ")
            : "None";

        const managerName = agent.manager_id
            ? this.agents[agent.manager_id]?.name || "Unknown"
            : "None";

        content.innerHTML = `
            <div class="agent-details">
                <div class="detail-group">
                    <h4><i class="fas fa-user-tag"></i> Basic Information</h4>
                    <p><strong>Name:</strong> ${agent.name}</p>
                    <p><strong>Role:</strong> ${agent.role}</p>
                    <p><strong>Type:</strong> ${agent.type}</p>
                    <p><strong>Status:</strong> ${agent.status}</p>
                </div>
                
                <div class="detail-group">
                    <h4><i class="fas fa-brain"></i> Specialty</h4>
                    <p>${agent.specialty}</p>
                </div>
                
                <div class="detail-group">
                    <h4><i class="fas fa-sitemap"></i> Hierarchy</h4>
                    <p><strong>Manager:</strong> ${managerName}</p>
                    <p><strong>Subordinates:</strong> ${subordinatesList}</p>
                </div>
                
                <div class="detail-group">
                    <h4><i class="fas fa-tasks"></i> Current Task</h4>
                    <p>${agent.current_task || "No current task"}</p>
                </div>
                
                <div class="detail-group">
                    <h4><i class="fas fa-code"></i> Work Output</h4>
                    <div class="work-output">
                        <pre>${agent.work_output || "No output yet"}</pre>
                    </div>
                </div>
                
                <div class="detail-group">
                    <h4><i class="fas fa-comments"></i> Recent Messages</h4>
                    <div class="agent-messages">
                        ${this.getAgentMessages(agent.id)
                            .slice(-5)
                            .map(
                                (msg) => `
                            <div class="mini-message">
                                <span class="timestamp">${new Date(
                                    msg.timestamp
                                ).toLocaleTimeString()}</span>
                                <span class="content">${msg.content}</span>
                            </div>
                        `
                            )
                            .join("")}
                    </div>
                </div>
            </div>
        `;

        modal.classList.add("active");
    }

    getAgentMessages(agentId) {
        return this.messages.filter(
            (msg) =>
                msg.from_agent_id === agentId || msg.to_agent_id === agentId
        );
    }

    deleteCurrentAgent() {
        if (this.currentAgent) {
            this.deleteAgent(this.currentAgent.id);
        }
    }

    sendMessage() {
        const toId = document.getElementById("message-to").value;
        const content = document.getElementById("message-content").value.trim();
        if (!toId || !content) {
            alert("Please select a recipient and enter a message");
            return;
        }
        // Always send as user
        fetch(`/api/agents/${toId}/user_message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
        })
            .then((response) => {
                if (response.ok) {
                    document.getElementById("message-content").value = "";
                    this.loadMessages();
                } else {
                    alert("Failed to send user message");
                }
            })
            .catch(() => alert("Failed to send user message"));
    }

    async loadMessages() {
        try {
            const response = await fetch("/api/messages");
            const data = await response.json();
            this.messages = data.messages;
            this.updateMessagesView();
        } catch (error) {
            console.error("Failed to load messages:", error);
        }
    }

    clearMessages() {
        if (confirm("Are you sure you want to clear all messages?")) {
            this.messages = [];
            this.updateMessagesView();
        }
    }

    clearForm() {
        document.getElementById("agent-name").value = "";
        document.getElementById("agent-role").value = "";
        document.getElementById("agent-type").value = "worker";
        document.getElementById("agent-specialty").value = "";
        document.getElementById("agent-manager").value = "";
    }

    updateSystemStatus(status, type) {
        const statusBtn = document.getElementById("system-status");
        const icons = {
            success: "fas fa-check-circle",
            working: "fas fa-spinner fa-spin",
            error: "fas fa-exclamation-triangle",
            idle: "fas fa-pause-circle",
        };

        const colors = {
            success: "btn-success",
            working: "btn-warning",
            error: "btn-danger",
            idle: "btn-secondary",
        };

        statusBtn.className = `btn ${colors[type] || "btn-secondary"}`;
        statusBtn.innerHTML = `<i class="${
            icons[type] || "fas fa-question-circle"
        }"></i> ${status}`;
    }

    showLoading() {
        document.getElementById("loading-overlay").classList.add("active");
    }

    hideLoading() {
        document.getElementById("loading-overlay").classList.remove("active");
    }

    // Utility methods
    formatTimestamp(timestamp) {
        return new Date(timestamp).toLocaleString();
    }

    generateUniqueId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2);
    }

    // Animation helpers
    animateAgentStatus(agentId, status) {
        const node = document.querySelector(`[data-agent-id="${agentId}"]`);
        if (node) {
            node.classList.remove("idle", "working", "completed", "error");
            node.classList.add(status);
        }
    }

    // Export/Import functionality
    exportSystemState() {
        const state = {
            agents: this.agents,
            messages: this.messages,
            systemRunning: this.systemRunning,
            timestamp: new Date().toISOString(),
        };

        const blob = new Blob([JSON.stringify(state, null, 2)], {
            type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `multi-agent-system-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    importSystemState(file) {
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const state = JSON.parse(e.target.result);
                this.agents = state.agents || {};
                this.messages = state.messages || [];
                this.updateUI();
                alert("System state imported successfully");
            } catch (error) {
                alert("Failed to import system state: Invalid file format");
            }
        };
        reader.readAsText(file);
    }

    // Performance monitoring
    startPerformanceMonitoring() {
        setInterval(() => {
            const stats = {
                agentCount: Object.keys(this.agents).length,
                messageCount: this.messages.length,
                activeAgents: Object.values(this.agents).filter(
                    (a) => a.status === "working"
                ).length,
                memory: performance.memory
                    ? Math.round(
                          performance.memory.usedJSHeapSize / 1024 / 1024
                      )
                    : "N/A",
            };

            console.log("Performance Stats:", stats);
        }, 30000); // Every 30 seconds
    }

    async loadFileTree() {
        const container = document.getElementById("file-tree-container");
        container.innerHTML = "<div>Loading file tree...</div>";
        try {
            const res = await fetch("/api/project/files");
            const data = await res.json();
            container.innerHTML = "";
            container.appendChild(this.renderFileTree(data.tree, ""));
        } catch (e) {
            container.innerHTML = "<div>Error loading file tree.</div>";
        }
    }

    renderFileTree(tree, parentPath) {
        const ul = document.createElement("ul");
        ul.className = "file-tree";
        for (const node of tree) {
            const li = document.createElement("li");
            if (node.type === "folder") {
                const folderSpan = document.createElement("span");
                folderSpan.className = "file-folder";
                folderSpan.textContent = `📁 ${node.name}`;
                folderSpan.style.cursor = "pointer";
                folderSpan.onclick = async () => {
                    if (li.classList.contains("expanded")) {
                        li.classList.remove("expanded");
                        if (li.querySelector("ul"))
                            li.removeChild(li.querySelector("ul"));
                    } else {
                        li.classList.add("expanded");
                        if (!li.querySelector("ul")) {
                            const loading = document.createElement("div");
                            loading.textContent = "Loading...";
                            li.appendChild(loading);
                            const res = await fetch(
                                `/api/project/files?path=${encodeURIComponent(
                                    parentPath + node.name + "/"
                                )}`
                            );
                            const data = await res.json();
                            li.removeChild(loading);
                            li.appendChild(
                                this.renderFileTree(
                                    data.tree,
                                    parentPath + node.name + "/"
                                )
                            );
                        }
                    }
                };
                li.appendChild(folderSpan);
            } else {
                const filePath = parentPath + node.name;
                const fileLink = document.createElement("span");
                fileLink.className = "file-link";
                fileLink.textContent = `📄 ${node.name}`;
                fileLink.style.cursor = "pointer";
                fileLink.onclick = () => this.previewFile(filePath);
                li.appendChild(fileLink);
            }
            ul.appendChild(li);
        }
        return ul;
    }

    async previewFile(filePath) {
        const preview = document.getElementById("file-preview-container");
        preview.innerHTML = "<div>Loading file...</div>";
        try {
            const res = await fetch(
                `/api/project/file?path=${encodeURIComponent(filePath)}`
            );
            const data = await res.json();
            if (data.content !== undefined) {
                preview.innerHTML = `<h4>${filePath}</h4><pre style="background:#f5f5f5;padding:1em;overflow:auto;">${this.escapeHtml(
                    data.content
                )}</pre>`;
            } else {
                preview.innerHTML = "<div>Error loading file.</div>";
            }
        } catch (e) {
            preview.innerHTML = "<div>Error loading file.</div>";
        }
    }

    escapeHtml(text) {
        return text.replace(/[&<>"']/g, function (c) {
            return {
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            }[c];
        });
    }

    async loadDetailedLog() {
        const logDiv = document.getElementById("detailed-log");
        if (!logDiv) return;
        logDiv.innerHTML = '<div style="color:#aaa;">Loading log...</div>';
        try {
            const res = await fetch("/api/log");
            const data = await res.json();
            logDiv.innerHTML = "";
            for (const entry of data.log) {
                const line = document.createElement("div");
                line.style.fontFamily = "monospace";
                line.style.whiteSpace = "pre-wrap";
                line.style.padding = "2px 0";
                line.style.color = "#00ff90";
                if (entry.event === "project_started")
                    line.style.color = "#00bfff";
                if (entry.event === "agent_communication")
                    line.style.color = "#fffa65";
                line.textContent = `[${new Date(
                    entry.timestamp
                ).toLocaleTimeString()}] $ ${entry.description}`;
                logDiv.appendChild(line);
            }
            logDiv.scrollTop = logDiv.scrollHeight;
        } catch (e) {
            logDiv.innerHTML =
                '<div style="color:#f55;">Error loading log.</div>';
        }
    }

    openManualTaskModal() {
        const modal = document.getElementById("manual-task-modal");
        const agentSelect = document.getElementById("manual-task-agent");
        agentSelect.innerHTML = "";
        Object.values(this.agents).forEach((agent) => {
            const option = document.createElement("option");
            option.value = agent.id;
            option.textContent = `${agent.name} (${agent.role})`;
            agentSelect.appendChild(option);
        });
        document.getElementById("manual-task-content").value = "";
        modal.classList.add("active");
    }

    assignManualTask() {
        const agentId = document.getElementById("manual-task-agent").value;
        const task = document
            .getElementById("manual-task-content")
            .value.trim();
        if (!agentId || !task) {
            alert("Please select an agent and enter a task");
            return;
        }
        fetch(`/api/agents/${agentId}/assign_task`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task }),
        })
            .then((response) => {
                if (response.ok) {
                    closeManualTaskModal();
                } else {
                    alert("Failed to assign task");
                }
            })
            .catch(() => alert("Failed to assign task"));
    }

    pollMetrics() {
        this.updateMetrics();
        setInterval(() => this.updateMetrics(), 2000);
    }

    async updateMetrics() {
        try {
            const response = await fetch("/api/metrics");
            if (!response.ok) return;
            const data = await response.json();
            document.getElementById("active-agents-count").textContent =
                data.active_agents;
            document.getElementById("tasks-completed").textContent =
                data.tasks_completed;
            document.getElementById("messages-sent").textContent =
                data.messages_sent;
            document.getElementById("system-uptime").textContent =
                this.formatUptime(data.system_uptime);
        } catch (e) {
            // Optionally show error
        }
    }

    formatUptime(seconds) {
        const h = Math.floor(seconds / 3600)
            .toString()
            .padStart(2, "0");
        const m = Math.floor((seconds % 3600) / 60)
            .toString()
            .padStart(2, "0");
        const s = (seconds % 60).toString().padStart(2, "0");
        return `${h}:${m}:${s}`;
    }
}

// Global app instance
let app;

// Initialize the application when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
    app = new MultiAgentApp();

    // Add some global helper functions
    window.createAgent = () => app.createAgent();
    window.closeModal = () => app.closeModal();
    window.app = app; // Make app globally accessible for inline event handlers

    // Start performance monitoring
    app.startPerformanceMonitoring();
});

// Global error handler
window.addEventListener("error", (e) => {
    console.error("Global error:", e.error);
    if (app) {
        app.hideLoading();
    }
});

// Handle WebSocket reconnection
window.addEventListener("online", () => {
    if (app && app.socket) {
        app.socket.connect();
    }
});

window.addEventListener("offline", () => {
    if (app) {
        app.updateSystemStatus("Offline", "error");
    }
});
