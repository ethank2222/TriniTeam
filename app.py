from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import json
import uuid
import threading
import time
import asyncio
import aiohttp
import os
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
import zipfile
import io
import re
import logging
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import traceback
from pathlib import Path
import tempfile
import shutil

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    logger.error("ANTHROPIC_API_KEY not found in environment variables")
    logger.error("Please set the ANTHROPIC_API_KEY environment variable")
    logger.error("You can set it by running: export ANTHROPIC_API_KEY='your-api-key-here'")
    raise ValueError("ANTHROPIC_API_KEY is required")

# Validate API key format
if not ANTHROPIC_API_KEY.startswith('sk-ant-'):
    logger.error("ANTHROPIC_API_KEY appears to be invalid (should start with 'sk-ant-')")
    logger.error("Please check your API key and try again")
    raise ValueError("ANTHROPIC_API_KEY appears to be invalid")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Thread pool for async operations
executor = ThreadPoolExecutor(max_workers=10)

# In-memory storage - no databases needed
class MemoryStore:
    def __init__(self):
        self.agents = {}
        self.tasks = {}
        self.messages = []
        self.projects = {}
        self.system_metrics = {
            'start_time': time.time(),
            'tasks_processed': 0,
            'messages_sent': 0,
            'files_created': 0,
            'api_calls': 0,
            'errors': 0
        }
        self.lock = threading.Lock()
    
    def clear(self):
        """Clear all stored data"""
        with self.lock:
            self.agents.clear()
            self.tasks.clear()
            self.messages.clear()
            self.projects.clear()
            self.system_metrics = {
                'start_time': time.time(),
                'tasks_processed': 0,
                'messages_sent': 0,
                'files_created': 0,
                'api_calls': 0,
                'errors': 0
            }

# Global memory store
memory_store = MemoryStore()

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"

class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    ERROR = "error"
    REVIEWING = "reviewing"

@dataclass
class Task:
    id: str
    description: str
    agent_id: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 1
    dependencies: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output: str = ""
    files_created: List[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""

@dataclass
class Agent:
    id: str
    name: str
    role: str
    agent_type: str
    specialty: str
    status: AgentStatus = AgentStatus.IDLE
    manager_id: Optional[str] = None
    subordinates: List[str] = field(default_factory=list)
    current_task_id: Optional[str] = None
    work_output: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    skills: List[str] = field(default_factory=list)
    performance_metrics: Dict[str, Any] = field(default_factory=lambda: {
        'tasks_completed': 0,
        'avg_completion_time': 0,
        'success_rate': 1.0,
        'quality_score': 85
    })

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'type': self.agent_type,
            'specialty': self.specialty,
            'status': self.status.value,
            'manager_id': self.manager_id,
            'subordinates': self.subordinates,
            'current_task_id': self.current_task_id,
            'work_output': self.work_output,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'skills': self.skills,
            'performance_metrics': self.performance_metrics
        }

@dataclass
class Project:
    id: str
    name: str
    description: str
    status: str = "idle"
    created_at: datetime = field(default_factory=datetime.now)
    files: Dict[str, str] = field(default_factory=dict)  # filename -> content
    temp_dir: Optional[str] = None

class AnthropicClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        self.session = None
        self.request_count = 0
        self.error_count = 0

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def generate_response(self, system_prompt: str, user_message: str, 
                              max_tokens: int = 2000, temperature: float = 0.7) -> str:
        """Generate AI response - only external API call"""
        try:
            session = await self._get_session()
            
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}]
            }
            
            self.request_count += 1
            memory_store.system_metrics['api_calls'] += 1
            logger.info(f"Making API request #{self.request_count}")
            logger.info(f"📝 Request payload: {len(system_prompt)} chars system prompt, {len(user_message)} chars user message")
            
            async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    response_text = result['content'][0]['text']
                    logger.info(f"✅ API response received: {len(response_text)} chars")
                    return response_text
                else:
                    error_text = await response.text()
                    logger.error(f"API Error: {response.status} - {error_text}")
                    self.error_count += 1
                    memory_store.system_metrics['errors'] += 1
                    return f"[API Error] Status: {response.status} - {error_text}"
                    
        except Exception as e:
            logger.error(f"Error calling Anthropic API: {e}")
            logger.error(f"🔍 Full error details: {str(e)}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            self.error_count += 1
            memory_store.system_metrics['errors'] += 1
            return f"[Error] {str(e)}"

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

class TaskQueue:
    def __init__(self):
        self.pending_tasks: List[str] = []
        self.in_progress_tasks: Set[str] = set()
        self.completed_tasks: Set[str] = set()
        self.failed_tasks: Set[str] = set()
        self.dependency_graph: Dict[str, Set[str]] = {}
        self._lock = threading.Lock()

    def add_task(self, task: Task):
        with self._lock:
            memory_store.tasks[task.id] = task
            self.pending_tasks.append(task.id)
            self.dependency_graph[task.id] = set(task.dependencies)
            logger.info(f"📝 Task added: {task.id} - {task.description[:50]}... (Agent: {task.agent_id})")
            logger.info(f"📊 Queue status: {len(self.pending_tasks)} pending, {len(self.in_progress_tasks)} in progress")
            
            # Debug: Show all pending tasks
            logger.debug(f"📋 All pending tasks: {[memory_store.tasks[tid].description[:30] for tid in self.pending_tasks]}")

    def get_ready_tasks(self) -> List[Task]:
        with self._lock:
            ready_tasks = []
            logger.info(f"🔍 Checking {len(self.pending_tasks)} pending tasks")
            
            if not self.pending_tasks:
                logger.info("📋 No pending tasks available")
                return ready_tasks
                
            for task_id in self.pending_tasks[:]:
                task = memory_store.tasks.get(task_id)
                if not task:
                    logger.warning(f"⚠️ Task {task_id} not found in memory store")
                    self.pending_tasks.remove(task_id)
                    continue
                
                # Check if task has an agent assigned
                if not task.agent_id:
                    logger.warning(f"⚠️ Task {task_id} has no agent assigned")
                    continue
                
                # Check if agent exists and is active
                agent = memory_store.agents.get(task.agent_id)
                if not agent:
                    logger.warning(f"⚠️ Task {task_id} assigned to non-existent agent {task.agent_id}")
                    continue
                
                if not agent.is_active:
                    logger.warning(f"⚠️ Task {task_id} assigned to inactive agent {agent.name}")
                    continue
                
                # Check dependencies
                if self._are_dependencies_satisfied(task_id):
                    ready_tasks.append(task)
                    self.pending_tasks.remove(task_id)
                    self.in_progress_tasks.add(task_id)
                    task.status = TaskStatus.IN_PROGRESS
                    task.started_at = datetime.now()
                    logger.info(f"✅ Task {task_id} is ready and moved to in_progress")
                    logger.info(f"📝 Task details: {task.description[:50]}... (Agent: {agent.name})")
                else:
                    dependencies = self.dependency_graph.get(task_id, set())
                    logger.debug(f"⏳ Task {task_id} dependencies not satisfied: {dependencies}")
                    # For tasks with no dependencies, consider them ready anyway
                    if not dependencies:
                        logger.info(f"🔄 Task {task_id} has no dependencies, considering ready")
                        ready_tasks.append(task)
                        self.pending_tasks.remove(task_id)
                        self.in_progress_tasks.add(task_id)
                        task.status = TaskStatus.IN_PROGRESS
                        task.started_at = datetime.now()
                        logger.info(f"✅ Task {task_id} moved to in_progress (no dependencies)")
                        logger.info(f"📝 Task details: {task.description[:50]}... (Agent: {agent.name})")
            
            logger.info(f"📋 Found {len(ready_tasks)} ready tasks")
            return sorted(ready_tasks, key=lambda t: t.priority, reverse=True)

    def complete_task(self, task_id: str, output: str = "", files_created: List[str] = None):
        with self._lock:
            if task_id in self.in_progress_tasks:
                self.in_progress_tasks.remove(task_id)
                self.completed_tasks.add(task_id)
                task = memory_store.tasks[task_id]
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                task.output = output
                task.files_created = files_created or []
                memory_store.system_metrics['tasks_processed'] += 1
                logger.info(f"Task completed: {task_id}")

    def fail_task(self, task_id: str, error: str = ""):
        with self._lock:
            if task_id in self.in_progress_tasks:
                self.in_progress_tasks.remove(task_id)
                task = memory_store.tasks[task_id]
                task.retry_count += 1
                task.error_message = error
                
                if task.retry_count <= task.max_retries:
                    task.status = TaskStatus.PENDING
                    self.pending_tasks.append(task_id)
                    logger.info(f"Task retry {task.retry_count}/{task.max_retries}: {task_id}")
                else:
                    self.failed_tasks.add(task_id)
                    task.status = TaskStatus.FAILED
                    logger.error(f"Task failed permanently: {task_id} - {error}")

    def _are_dependencies_satisfied(self, task_id: str) -> bool:
        dependencies = self.dependency_graph.get(task_id, set())
        return all(dep_id in self.completed_tasks for dep_id in dependencies)

    def get_status(self) -> Dict[str, int]:
        with self._lock:
            return {
                'pending': len(self.pending_tasks),
                'in_progress': len(self.in_progress_tasks),
                'completed': len(self.completed_tasks),
                'failed': len(self.failed_tasks)
            }

class EnhancedMultiAgentSystem:
    def __init__(self):
        self.task_queue = TaskQueue()
        self.anthropic_client = AnthropicClient(ANTHROPIC_API_KEY)
        self.system_running = False
        self.current_project = None
        self.processing_lock = threading.Lock()
        self.setup_default_agents()
        # Don't start background processing until project starts

    def setup_default_agents(self):
        """Setup default agents - stored in memory only"""
        # Manager Agent
        manager = Agent(
            id=str(uuid.uuid4()),
            name="ArchitectLead",
            role="Manager",
            agent_type="manager",
            specialty="System Architecture, Project Management, Code Review, Quality Assurance",
            skills=["Architecture", "Project Management", "Code Review", "Quality Assurance", "Integration"]
        )
        
        # Generalist Developer 1
        dev1 = Agent(
            id=str(uuid.uuid4()),
            name="Developer1",
            role="Full Stack Developer",
            agent_type="worker",
            specialty="Full Stack Development - Frontend, Backend, DevOps, Database, API Development",
            manager_id=manager.id,
            skills=["React", "TypeScript", "Python", "Flask", "Node.js", "Docker", "Database Design", "API Development", "UI/UX", "DevOps", "HTML", "CSS", "JavaScript", "Java", "C", "C++"]
        )
        
        # Generalist Developer 2
        dev2 = Agent(
            id=str(uuid.uuid4()),
            name="Developer2",
            role="Full Stack Developer",
            agent_type="worker",
            specialty="Full Stack Development - Frontend, Backend, DevOps, Database, API Development",
            manager_id=manager.id,
            skills=["React", "TypeScript", "Python", "Flask", "Node.js", "Docker", "Database Design", "API Development", "UI/UX", "DevOps", "HTML", "CSS", "JavaScript", "Java", "C", "C++"]
        )
        
        # Generalist Developer 3
        dev3 = Agent(
            id=str(uuid.uuid4()),
            name="Developer3",
            role="Full Stack Developer",
            agent_type="worker",
            specialty="Full Stack Development - Frontend, Backend, DevOps, Database, API Development",
            manager_id=manager.id,
            skills=["React", "TypeScript", "Python", "Flask", "Node.js", "Docker", "Database Design", "API Development", "UI/UX", "DevOps", "HTML", "CSS", "JavaScript", "Java", "C", "C++"]
        )
        
        # Set up relationships
        manager.subordinates = [dev1.id, dev2.id, dev3.id]
        
        # Store in memory
        memory_store.agents[manager.id] = manager
        memory_store.agents[dev1.id] = dev1
        memory_store.agents[dev2.id] = dev2
        memory_store.agents[dev3.id] = dev3
        
        logger.info(f"Default agents created: {len(memory_store.agents)} agents")

    def get_agent_prompts(self, agent: Agent) -> str:
        """Get specialized prompts for each agent type"""
        prompts = {
            "Manager": f"""You are {agent.name}, a Senior Technical Lead and Project Manager.

CORE RESPONSIBILITIES:
- Design system architecture and break down complex projects into tasks
- Review code quality and ensure best practices
- Coordinate team members and manage project flow
- Ensure all requirements are met and deliverables are complete

WORKFLOW:
1. For initial planning: Create task breakdown and assign to workers
2. For review tasks: Review completed work and mark as complete

TASK ASSIGNMENT FORMAT:
When creating tasks, use this JSON format with the EXACT agent names:
```json
{{
    "tasks": [
        {{
            "agent": "Developer1",
            "description": "Detailed task description",
            "priority": 1-10,
            "dependencies": [],
            "files_expected": ["file1.py", "file2.js"]
        }}
    ]
}}
```

AVAILABLE AGENTS:
- Developer1 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development
- Developer2 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development
- Developer3 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development

IMPORTANT: Use the exact agent names: "Developer1", "Developer2", or "Developer3"

QUALITY STANDARDS:
- Code must follow best practices and be production-ready
- All functions must have proper error handling
- Files must be properly structured and documented
- Security considerations must be addressed

REVIEW PROCESS:
- For review tasks, examine the completed work and files created
- Check if the task meets requirements and quality standards
- Mark as complete if satisfied, or provide feedback if not

IMPORTANT: After providing the task assignments in JSON format, end your response with "TASK COMPLETED" to indicate completion.

Your specialty: {agent.specialty}""",

            "Full Stack Developer": f"""You are {agent.name}, a Senior Full Stack Developer.

TECHNICAL EXPERTISE:
- Frontend: React/TypeScript, HTML/CSS, JavaScript, modern web development
- Backend: Python/Flask, Node.js, Java, API development, database design
- Systems: C, C++, low-level programming, performance optimization
- DevOps: Docker, CI/CD, cloud deployment, monitoring
- Database: SQL, NoSQL, data modeling, optimization
- Security: Authentication, authorization, data protection

DEVELOPMENT STANDARDS:
- Write clean, maintainable, production-ready code
- Implement proper error handling and validation
- Follow best practices for security and performance
- Use modern development patterns and tools
- Include comprehensive documentation and comments

OUTPUT FORMAT:
- Always provide complete, working code
- Include proper imports and dependencies
- Add comprehensive comments
- Ensure code is production-ready
- ALWAYS use this exact format for files: ```filename: path/to/file.ext

EXAMPLE FILE FORMATS:

Frontend (React/TypeScript):
```filename: src/components/App.tsx
import React from 'react';

interface AppProps {{
  title: string;
}}

export const App: React.FC<AppProps> = ({{ title }}) => {{
  return (
    <div className="app">
      <header className="App-header">
        <h1>{{title}}</h1>
      </header>
    </div>
  );
}};
```

Backend (Python/Flask):
```filename: app.py
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({{'status': 'healthy'}})

if __name__ == '__main__':
    app.run(debug=True)
```

DevOps (Docker):
```filename: docker-compose.yml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
```

IMPORTANT: Always use the exact format ```filename: path/to/file.ext for each file you create.

Your specialty: {agent.specialty}
Always end your response with "TASK COMPLETED" when finished."""
        }
        
        return prompts.get(agent.role, prompts["Manager"])

    async def start_project(self, project_description: str):
        """Start a new project - all data stored in memory"""
        try:
            self.current_project = project_description
            self.system_running = True
            
            # Create project in memory
            project = Project(
                id=str(uuid.uuid4()),
                name=f"Project_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                description=project_description,
                status="running"
            )
            
            # Create temporary directory for files
            project.temp_dir = tempfile.mkdtemp(prefix="multiagent_")
            
            memory_store.projects[project.id] = project
            
            # Reset system state
            self.task_queue = TaskQueue()
            memory_store.messages = []
            
            # Reset agent states
            for agent in memory_store.agents.values():
                agent.status = AgentStatus.IDLE
                agent.current_task_id = None
                agent.work_output = ""
                agent.last_activity = datetime.now()
            
            # Create initial planning task for manager ONLY
            manager = next(agent for agent in memory_store.agents.values() if agent.agent_type == "manager")
            
            planning_task = Task(
                id=str(uuid.uuid4()),
                description=f"""PROJECT PLANNING AND ARCHITECTURE

Project Description: {project_description}

Your task is to:
1. Analyze the project requirements
2. Design the system architecture
3. Create a detailed task breakdown for each team member
4. Define file structure and deliverables
5. Specify quality requirements and testing approach

Please provide:
- A comprehensive project plan
- Task assignments in JSON format for each agent
- Expected file structure
- Quality and testing requirements
- Timeline and milestones

The team consists of:
- Developer1 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development
- Developer2 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development
- Developer3 (Full Stack Developer) - Frontend, Backend, DevOps, Database, API Development

Create tasks that will result in a complete, production-ready application.

IMPORTANT: After providing the task assignments in JSON format, end your response with "TASK COMPLETED" to indicate completion.""",
                agent_id=manager.id,
                priority=10
            )
            
            self.task_queue.add_task(planning_task)
            logger.info(f"📝 Initial planning task added: {planning_task.id}")
            logger.info(f"📊 Task queue status after adding initial task: {self.task_queue.get_status()}")
            
            # Immediately assign the planning task to the manager
            manager.status = AgentStatus.WORKING
            manager.current_task_id = planning_task.id
            manager.last_activity = datetime.now()
            
            # Move task to in_progress immediately
            if planning_task.id in self.task_queue.pending_tasks:
                self.task_queue.pending_tasks.remove(planning_task.id)
            self.task_queue.in_progress_tasks.add(planning_task.id)
            planning_task.status = TaskStatus.IN_PROGRESS
            planning_task.started_at = datetime.now()
            
            logger.info(f"👨‍💼 Immediately assigned planning task to {manager.name}")
            logger.info(f"📊 Task queue status after assignment: {self.task_queue.get_status()}")
            
            # Start background processing
            self.start_background_processing()
            
            # Immediately process the planning task
            logger.info(f"🎯 Immediately processing planning task for {manager.name}")
            self._process_task_sync(manager, planning_task)
            
            # Emit project started event
            socketio.emit('project_started', {
                'project': self.current_project,
                'project_id': project.id,
                'agents': {aid: agent.to_dict() for aid, agent in memory_store.agents.items()}
            })
            
            logger.info(f"Project started: {project_description[:50]}...")
            return True
            
        except Exception as e:
            logger.error(f"Error starting project: {e}")
            return False

    def start_background_processing(self):
        """Start background task processing"""
        def process_tasks():
            logger.info("🔄 Background task processing loop started")
            while True:
                try:
                    if self.system_running:
                        # First, aggressively assign any unassigned tasks to idle workers
                        self._assign_tasks_to_idle_workers()
                        
                        # Aggressively scavenge for unassigned tasks
                        self._scavenge_unassigned_tasks()
                        
                        # Force assign any remaining tasks to idle workers
                        self._force_assign_to_idle_workers()
                        
                        # Process any ready tasks (tasks that are already assigned and ready)
                        ready_tasks = self.task_queue.get_ready_tasks()
                        
                        if ready_tasks:
                            logger.info(f"📋 Processing {len(ready_tasks)} ready tasks")
                            
                            # Process tasks in parallel using threads
                            threads = []
                            for task in ready_tasks:
                                agent = memory_store.agents.get(task.agent_id)
                                if agent and agent.is_active:
                                    # Create a thread for each task
                                    thread = threading.Thread(
                                        target=self._process_task_sync,
                                        args=(agent, task)
                                    )
                                    threads.append(thread)
                                    thread.start()
                                else:
                                    logger.warning(f"⚠️ Agent {task.agent_id} not found or inactive")
                            
                            # Wait for all threads to complete
                            for thread in threads:
                                thread.join()
                        
                        # Also process any in-progress tasks that might be stuck
                        self._process_stuck_tasks()
                        
                        # Process any in-progress tasks that are assigned to working agents
                        self._process_in_progress_tasks()
                        
                        # Check for stuck agents and reset them
                        self._check_for_stuck_agents()
                        
                        # Check if all tasks are completed and trigger final review
                        self._check_project_completion()
                        
                        # Emit status updates
                        self._emit_status_update()
                        
                        # Debug: Log current state
                        task_status = self.task_queue.get_status()
                        idle_workers = [a for a in memory_store.agents.values() if a.agent_type == "worker" and a.status == AgentStatus.IDLE]
                        idle_manager = [a for a in memory_store.agents.values() if a.agent_type == "manager" and a.status == AgentStatus.IDLE]
                        working_agents = [a for a in memory_store.agents.values() if a.status == AgentStatus.WORKING]
                        
                        logger.debug(f"📊 Debug - Tasks: {task_status}, Idle workers: {len(idle_workers)}, Idle manager: {len(idle_manager)}, Working agents: {len(working_agents)}")
                        
                        # If we have working agents but no tasks being processed, force process them
                        if working_agents and task_status['in_progress'] > 0:
                            logger.info(f"🔄 Found {len(working_agents)} working agents with {task_status['in_progress']} in-progress tasks, forcing processing")
                            self._force_process_in_progress_tasks()
                        
                        time.sleep(1)  # Check every 1 second for more responsiveness
                    else:
                        time.sleep(5)  # Wait longer when system not running
                    
                except Exception as e:
                    logger.error(f"🚨 Error in background processing: {e}")
                    import traceback
                    logger.error(f"🔍 Traceback: {traceback.format_exc()}")
                    time.sleep(5)  # Wait longer on error

        thread = threading.Thread(target=process_tasks, daemon=True)
        thread.start()
        logger.info("✅ Background task processing started")

    def _process_task_sync(self, agent: Agent, task: Task):
        """Synchronous task processing to avoid asyncio conflicts"""
        try:
            logger.info(f"🎯 Processing task for {agent.name}: {task.description[:50]}...")
            
            # Validate task and agent data
            if not self._validate_task_and_agent(agent, task):
                logger.error(f"❌ Invalid task or agent data, skipping task")
                return
            
            # Check if task has been running too long (timeout)
            if task.started_at:
                elapsed = (datetime.now() - task.started_at).total_seconds()
                if elapsed > 30:  # 30 seconds timeout for scavenging
                    logger.warning(f"⏰ Task {task.id} taking too long ({elapsed:.1f}s), may need scavenging")
                    # Don't force completion, just log for potential scavenging
                if elapsed > 300:  # 5 minutes absolute timeout
                    logger.warning(f"⏰ Task {task.id} timed out after {elapsed:.1f}s, forcing completion")
                    self.task_queue.complete_task(task.id, "Task completed due to timeout", [])
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
                    return
                if elapsed > 60:  # 1 minute warning
                    logger.warning(f"⏰ Task {task.id} taking longer than expected ({elapsed:.1f}s)")
            
            agent.status = AgentStatus.WORKING
            agent.current_task_id = task.id
            agent.last_activity = datetime.now()
            
            logger.info(f"🎯 Starting task processing for {agent.name}: {task.description[:50]}...")
            
            # Build context for the task
            context = self._build_task_context(agent, task)
            logger.info(f"📝 Built context for {agent.name}")
            
            # Get agent's specialized prompt
            system_prompt = self.get_agent_prompts(agent)
            logger.info(f"🤖 Using system prompt for {agent.name}")
            
            # Create a new event loop for this task
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                logger.info(f"🔄 Generating AI response for {agent.name}...")
                # Generate response
                response = loop.run_until_complete(
                    self.anthropic_client.generate_response(
                        system_prompt, context, max_tokens=3000, temperature=0.7
                    )
                )
                logger.info(f"✅ AI response generated for {agent.name} ({len(response)} chars)")
                
                # Check if response contains error indicators
                if response.startswith("[API Error]") or response.startswith("[Error]"):
                    logger.error(f"❌ API call failed for {agent.name}: {response}")
                    # Don't mark task as complete, let it retry
                    return
                
                # Update agent output
                agent.work_output += f"\n[{datetime.now().strftime('%H:%M:%S')}] {response}"
                
                # Extract files from response
                files_created = self._extract_files_from_response(response)
                if files_created:
                    logger.info(f"📁 Created {len(files_created)} files: {files_created}")
                else:
                    logger.warning(f"⚠️ No files were extracted from {agent.name}'s response")
                    logger.debug(f"📝 Response preview: {response[:200]}...")
                
                # Check if task is completed - be more strict
                task_completed = False
                
                # Check for explicit completion indicators
                if "TASK COMPLETED" in response:
                    task_completed = True
                    logger.info(f"✅ Task completed with explicit indicator")
                
                # For manager tasks, check if JSON was generated with proper structure
                elif agent.agent_type == "manager" and not task_completed:
                    json_patterns = [r'```json\s*\n(.*?)\n```', r'```\s*\n(.*?)\n```', r'\{.*?"tasks".*?\}']
                    for pattern in json_patterns:
                        if re.search(pattern, response, re.DOTALL):
                            # Additional validation: check if JSON actually contains task assignments
                            json_match = re.search(pattern, response, re.DOTALL)
                            if json_match:
                                try:
                                    json_str = json_match.group(1) if len(json_match.groups()) > 0 else json_match.group(0)
                                    task_data = json.loads(json_str)
                                    if "tasks" in task_data and isinstance(task_data["tasks"], list) and len(task_data["tasks"]) > 0:
                                        task_completed = True
                                        logger.info(f"👨‍💼 Manager task considered complete due to valid JSON task assignments")
                                        break
                                except json.JSONDecodeError:
                                    logger.debug(f"❌ JSON found but invalid, not marking complete")
                                    continue
                
                # For final review, check for project completion
                elif agent.agent_type == "manager" and "FINAL PROJECT REVIEW" in task.description and not task_completed:
                    if "PROJECT COMPLETED" in response:
                        task_completed = True
                        logger.info(f"👨‍💼 Final review completed, project ready for delivery")
                        # Mark project as ready for completion
                        self._mark_project_ready_for_completion()
                
                # For worker tasks, only consider complete if they generated files AND have substantial response
                elif agent.agent_type == "worker" and not task_completed and files_created and len(response.strip()) > 100:
                    task_completed = True
                    logger.info(f"👷 Worker task considered complete due to file creation and substantial response")
                
                # For any task, check if it's substantially complete
                elif not task_completed and len(response.strip()) > 500 and self._is_task_complete(response):
                    task_completed = True
                    logger.info(f"✅ Task considered complete due to substantial response and completion indicators")
                
                if task_completed:
                    # If no files were created but this is a worker agent, try to create basic files
                    if not files_created and agent.agent_type == "worker":
                        logger.info(f"🔄 No files created by {agent.name}, creating basic files...")
                        files_created = self._create_basic_files_for_agent(agent, task)
                    
                    self.task_queue.complete_task(task.id, response, files_created)
                    agent.status = AgentStatus.IDLE  # Reset to idle so it can pick up new tasks
                    agent.current_task_id = None
                    agent.performance_metrics['tasks_completed'] += 1
                    
                    # Handle manager tasks (task creation)
                    if agent.agent_type == "manager":
                        logger.info(f"👨‍💼 Manager {agent.name} completed task, handling response...")
                        loop.run_until_complete(self._handle_manager_response(agent, response))
                    
                    # Notify completion
                    loop.run_until_complete(
                        self._send_message(agent.id, None, f"Task completed: {task.description[:50]}...", "task_completion")
                    )
                    
                    logger.info(f"🎉 Task completed for {agent.name}")
                    
                    # Immediately try to assign new task to this worker
                    if agent.agent_type == "worker":
                        logger.info(f"🔄 Worker {agent.name} completed task, looking for next task...")
                        # Immediately check for new tasks to assign
                        self._immediately_assign_next_task(agent)
                    
                else:
                    # Task is still in progress - don't create retry task yet
                    logger.info(f"⏳ Task still in progress for {agent.name}, continuing...")
                    
                    # Only create new tasks from manager responses
                    if agent.agent_type == "manager":
                        loop.run_until_complete(self._create_tasks_from_response(agent, response))
                    
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"❌ Error processing task for {agent.name}: {e}")
            self.task_queue.fail_task(task.id, str(e))
            agent.status = AgentStatus.IDLE  # Reset to idle so it can pick up new tasks
            agent.current_task_id = None

    def _build_task_context(self, agent: Agent, task: Task) -> str:
        """Build context for task execution"""
        context = f"""CURRENT TASK: {task.description}

PROJECT CONTEXT:
- Project: {self.current_project}
- Task Priority: {task.priority}

SYSTEM STATUS:
- Total Tasks: {len(memory_store.tasks)}
- Completed Tasks: {len(self.task_queue.completed_tasks)}
- Your Role: {agent.role}
- Your Specialty: {agent.specialty}
"""
        
        # Add available agents for manager tasks
        if agent.agent_type == "manager":
            context += "\nAVAILABLE TEAM MEMBERS:\n"
            for a in memory_store.agents.values():
                if a.agent_type == "worker":
                    context += f"- {a.name} ({a.role}) - {a.specialty}\n"
            context += "\nUse the exact agent names when creating tasks.\n"
            context += "All workers are full-stack developers and can handle any type of task.\n"
        
        # Add current project files if available
        current_project = next((p for p in memory_store.projects.values() if p.status == "running"), None)
        if current_project and current_project.files:
            context += f"\nCURRENT PROJECT FILES:\n"
            for filename in current_project.files.keys():
                context += f"- {filename}\n"
        
        # Add recent messages
        recent_messages = memory_store.messages[-5:]
        if recent_messages:
            context += "\nRECENT TEAM COMMUNICATIONS:\n"
            for msg in recent_messages:
                context += f"- {msg.get('content', '')[:100]}...\n"
        
        return context

    def _extract_files_from_response(self, response: str) -> List[str]:
        """Extract and save files from AI response to current project"""
        files_created = []
        
        current_project = next((p for p in memory_store.projects.values() if p.status == "running"), None)
        if not current_project:
            logger.warning("⚠️ No running project found for file extraction")
            return files_created
        
        # Clean the response first
        cleaned_response = self._clean_and_validate_response(response)
        
        logger.info(f"🔍 Extracting files from response ({len(cleaned_response)} chars)")
        logger.debug(f"📝 Response preview: {cleaned_response[:500]}...")
        
        # Enhanced patterns to catch more file formats
        patterns = [
            # Pattern 1: ```language filename: path/to/file.ext
            r'```(?:[\w+]+)?\s*filename:\s*([^\n]+)\n(.*?)```',
            # Pattern 2: ```path/to/file.ext (language)
            r'```([^\n]+\.(?:py|js|jsx|ts|tsx|css|html|json|yml|yaml|md|txt|sh|dockerfile|sql|xml|env|gitignore|dockerignore|nvmrc|package\.json|requirements\.txt|README\.md))\n(.*?)```',
            # Pattern 3: filename: path/to/file.ext\n```language\n
            r'filename:\s*([^\n]+\.(?:py|js|jsx|ts|tsx|css|html|json|yml|yaml|md|txt|sh|dockerfile|sql|xml|env|gitignore|dockerignore|nvmrc|package\.json|requirements\.txt|README\.md))\n```(?:[\w+]+)?\n(.*?)```',
            # Pattern 4: File: path/to/file.ext\n```language\n
            r'File:\s*([^\n]+\.(?:py|js|jsx|ts|tsx|css|html|json|yml|yaml|md|txt|sh|dockerfile|sql|xml|env|gitignore|dockerignore|nvmrc|package\.json|requirements\.txt|README\.md))\n```(?:[\w+]+)?\n(.*?)```',
            # Pattern 5: Create file: path/to/file.ext\n```language\n
            r'Create file:\s*([^\n]+\.(?:py|js|jsx|ts|tsx|css|html|json|yml|yaml|md|txt|sh|dockerfile|sql|xml|env|gitignore|dockerignore|nvmrc|package\.json|requirements\.txt|README\.md))\n```(?:[\w+]+)?\n(.*?)```',
            # Pattern 6: Simple code blocks with common extensions
            r'```([^\n]+\.(?:py|js|jsx|ts|tsx|css|html|json|yml|yaml|md|txt|sh|dockerfile|sql|xml|env|gitignore|dockerignore|nvmrc|package\.json|requirements\.txt|README\.md))\n(.*?)```',
            # Pattern 7: Any code block that might contain a file (fallback)
            r'```(?:[\w+]+)?\n(.*?)```'
        ]
        
        for pattern_idx, pattern in enumerate(patterns):
            matches = re.findall(pattern, response, re.DOTALL)
            logger.debug(f"📋 Pattern {pattern_idx + 1} found {len(matches)} matches")
            
            for match in matches:
                if len(match) == 2:
                    filename, code = match
                    filename = filename.strip()
                    code = code.strip()
                    
                    # Skip empty code blocks
                    if not code or len(code) < 10:
                        logger.debug(f"⏭️ Skipping empty or too short code block")
                        continue
                    
                    # Clean up filename - remove any language specifiers
                    if ':' in filename:
                        filename = filename.split(':', 1)[1].strip()
                    
                    # For pattern 7 (fallback), try to infer filename from content
                    if pattern_idx == 6:  # Pattern 7
                        # Try to extract filename from the code content itself
                        filename = self._infer_filename_from_code(code)
                        if not filename:
                            logger.debug(f"⏭️ Could not infer filename from code, skipping")
                            continue
                    
                    # Ensure filename has proper extension
                    if not any(filename.endswith(ext) for ext in ['.py', '.js', '.jsx', '.ts', '.tsx', '.css', '.html', '.json', '.yml', '.yaml', '.md', '.txt', '.sh', '.dockerfile', '.sql', '.xml', '.env', '.gitignore', '.dockerignore', '.nvmrc']):
                        filename = self._infer_file_extension(filename, code)
                    
                    # Skip if we still don't have a valid filename
                    if not filename or filename == 'unknown':
                        logger.debug(f"⏭️ Invalid filename after processing: {filename}")
                        continue
                    
                    # Store file in project
                    current_project.files[filename] = code
                    files_created.append(filename)
                    memory_store.system_metrics['files_created'] += 1
                    
                    # Save to filesystem
                    self._save_file_to_filesystem(current_project, filename, code)
                    
                    # Also save to temp directory for backup
                    if current_project.temp_dir:
                        try:
                            file_path = Path(current_project.temp_dir) / filename
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(code)
                            logger.debug(f"💾 Saved to temp: {file_path}")
                        except Exception as e:
                            logger.error(f"❌ Error saving file {filename} to temp: {e}")
                    
                    logger.info(f"📁 Created file: {filename} ({len(code)} chars)")
        
        if files_created:
            logger.info(f"✅ Extracted {len(files_created)} files: {files_created}")
        else:
            logger.warning("⚠️ No files extracted from response")
            logger.debug(f"📝 Full response for debugging: {response}")
            
        return files_created

    def _infer_filename_from_code(self, code: str) -> str:
        """Try to infer filename from code content"""
        code_lower = code.lower()
        
        # Common patterns to identify file types
        if 'import ' in code and ('def ' in code or 'class ' in code):
            return 'app.py'
        elif 'function ' in code or 'const ' in code or 'let ' in code or 'var ' in code:
            if 'react' in code_lower or 'import react' in code_lower:
                return 'App.jsx'
            else:
                return 'app.js'
        elif '<html' in code_lower or '<!doctype' in code_lower:
            return 'index.html'
        elif '{' in code and '}' in code and ('"name"' in code or '"version"' in code):
            return 'package.json'
        elif 'from ' in code_lower and 'import ' in code_lower:
            return 'requirements.txt'
        elif 'version:' in code_lower or 'services:' in code_lower:
            return 'docker-compose.yml'
        elif 'from ' in code_lower and 'run ' in code_lower:
            return 'Dockerfile'
        else:
            return 'unknown'

    def _infer_file_extension(self, filename: str, code: str) -> str:
        """Infer file extension based on content"""
        code_lower = code.lower()
        
        if 'import ' in code or 'def ' in code or 'class ' in code:
            return filename + '.py'
        elif 'function ' in code or 'const ' in code or 'let ' in code or 'var ' in code:
            if 'react' in code_lower or 'import react' in code_lower:
                return filename + '.jsx'
            else:
                return filename + '.js'
        elif '<html' in code_lower or '<!doctype' in code_lower:
            return filename + '.html'
        elif '{' in code and '}' in code and ('"name"' in code or '"version"' in code):
            return filename + '.json'
        elif 'from ' in code_lower and 'run ' in code_lower:
            return filename + '.dockerfile'
        elif 'version:' in code_lower or 'services:' in code_lower:
            return filename + '.yml'
        else:
            return filename + '.txt'

    def _create_basic_files_for_agent(self, agent: Agent, task: Task) -> List[str]:
        """Create basic files for an agent if they didn't create any"""
        files_created = []
        current_project = next((p for p in memory_store.projects.values() if p.status == "running"), None)
        
        if not current_project:
            return files_created
        
        logger.info(f"🔄 Creating basic files for {agent.name} ({agent.role})")
        
        # For generalist workers, create a mix of files based on task description
        task_desc_lower = task.description.lower()
        
        # Determine what type of files to create based on task description
        if any(keyword in task_desc_lower for keyword in ["frontend", "react", "ui", "interface", "component"]):
            # Frontend-focused files
            files_created.extend([
                self._create_file(current_project, "src/App.jsx", self._get_basic_react_app()),
                self._create_file(current_project, "src/index.js", self._get_basic_react_index()),
                self._create_file(current_project, "public/index.html", self._get_basic_html()),
                self._create_file(current_project, "package.json", self._get_basic_package_json())
            ])
        elif any(keyword in task_desc_lower for keyword in ["backend", "api", "server", "flask", "python"]):
            # Backend-focused files
            files_created.extend([
                self._create_file(current_project, "app.py", self._get_basic_flask_app()),
                self._create_file(current_project, "requirements.txt", self._get_basic_requirements())
            ])
        elif any(keyword in task_desc_lower for keyword in ["docker", "deployment", "devops", "infrastructure"]):
            # DevOps-focused files
            files_created.extend([
                self._create_file(current_project, "Dockerfile", self._get_basic_dockerfile()),
                self._create_file(current_project, "docker-compose.yml", self._get_basic_docker_compose())
            ])
        else:
            # Default: create a basic project structure
            files_created.extend([
                self._create_file(current_project, "app.py", self._get_basic_flask_app()),
                self._create_file(current_project, "requirements.txt", self._get_basic_requirements()),
                self._create_file(current_project, "src/App.jsx", self._get_basic_react_app()),
                self._create_file(current_project, "package.json", self._get_basic_package_json())
            ])
        
        logger.info(f"✅ Created {len(files_created)} basic files for {agent.name}")
        return files_created

    def _create_file(self, project: Project, filename: str, content: str) -> str:
        """Create a file in the project"""
        project.files[filename] = content
        memory_store.system_metrics['files_created'] += 1
        logger.info(f"📁 Created basic file: {filename} ({len(content)} chars)")
        
        # Also save to file system
        self._save_file_to_filesystem(project, filename, content)
        
        return filename

    def _save_file_to_filesystem(self, project: Project, filename: str, content: str):
        """Save file to the actual file system"""
        try:
            # Create project directory if it doesn't exist
            project_dir = f"projects/{project.id}"
            os.makedirs(project_dir, exist_ok=True)
            
            # Create subdirectories if needed
            file_path = os.path.join(project_dir, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Write file to filesystem
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"💾 Saved to filesystem: {file_path}")
            
        except Exception as e:
            logger.error(f"❌ Error saving file to filesystem: {e}")

    def _get_basic_react_app(self) -> str:
        return '''import React from 'react';
import './App.css';

function App() {
  return (
    <div className="App">
      <header className="App-header">
        <h1>Welcome to React App</h1>
        <p>This is a basic React application.</p>
      </header>
    </div>
  );
}

export default App;'''

    def _get_basic_react_index(self) -> str:
        return '''import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);'''

    def _get_basic_html(self) -> str:
        return '''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>React App</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>'''

    def _get_basic_package_json(self) -> str:
        return '''{
  "name": "react-app",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build",
    "test": "react-scripts test",
    "eject": "react-scripts eject"
  }
}'''

    def _get_basic_flask_app(self) -> str:
        return '''from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({"message": "Welcome to Flask API"})

@app.route('/api/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)'''

    def _get_basic_requirements(self) -> str:
        return '''flask==2.3.3
flask-cors==4.0.0
python-dotenv==1.0.0'''

    def _get_basic_dockerfile(self) -> str:
        return '''FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]'''

    def _get_basic_docker_compose(self) -> str:
        return '''version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=development
    volumes:
      - .:/app'''

    def _create_basic_project_structure(self, project: Project):
        """Create a basic project structure with files from all agents"""
        logger.info(f"🔄 Creating basic project structure for project: {project.id}")
        
        # Create files from all agent types
        files_created = []
        
        # Frontend files
        files_created.extend([
            self._create_file(project, "src/App.jsx", self._get_basic_react_app()),
            self._create_file(project, "src/index.js", self._get_basic_react_index()),
            self._create_file(project, "public/index.html", self._get_basic_html()),
            self._create_file(project, "package.json", self._get_basic_package_json())
        ])
        
        # Backend files
        files_created.extend([
            self._create_file(project, "app.py", self._get_basic_flask_app()),
            self._create_file(project, "requirements.txt", self._get_basic_requirements())
        ])
        
        # DevOps files
        files_created.extend([
            self._create_file(project, "Dockerfile", self._get_basic_dockerfile()),
            self._create_file(project, "docker-compose.yml", self._get_basic_docker_compose())
        ])
        
        # Add a README
        readme_content = f"""# Project: {project.name}

This is a basic project structure created by the Multi-Agent System.

## Frontend
- React application in `src/` directory
- HTML template in `public/` directory

## Backend
- Flask API in `app.py`
- Dependencies in `requirements.txt`

## DevOps
- Docker configuration in `Dockerfile`
- Multi-service setup in `docker-compose.yml`

## Running the Project

### Frontend
```bash
cd frontend
npm install
npm start
```

### Backend
```bash
pip install -r requirements.txt
python app.py
```

### With Docker
```bash
docker-compose up --build
```
"""
        files_created.append(self._create_file(project, "README.md", readme_content))
        
        logger.info(f"✅ Created basic project structure with {len(files_created)} files")
        return files_created

    def is_project_ready_for_completion(self) -> bool:
        """Check if project is ready for completion (has been reviewed)"""
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        if current_project and current_project.status == "reviewed":
            return True
        return False

    def _are_dependencies_satisfied(self, task_id: str) -> bool:
        """Check if all dependencies for a task are satisfied"""
        task = memory_store.tasks.get(task_id)
        if not task:
            return False
        
        for dep_id in task.dependencies:
            if dep_id not in self.task_queue.completed_tasks:
                return False
        return True

    def _assign_tasks_to_idle_workers(self):
        """Assign tasks to idle workers - this is the main worker-driven assignment"""
        # Get idle workers
        idle_workers = [
            agent for agent in memory_store.agents.values() 
            if agent.agent_type == "worker" and agent.is_active and agent.status == AgentStatus.IDLE
        ]
        
        # Get idle manager
        idle_manager = next(
            (agent for agent in memory_store.agents.values() 
             if agent.agent_type == "manager" and agent.is_active and agent.status == AgentStatus.IDLE), 
            None
        )
        
        if not idle_workers and not idle_manager:
            logger.debug("⏸️ No idle workers or manager available")
            return
        
        # Get ALL available tasks (pending tasks that can be assigned)
        available_tasks = []
        manager_tasks = []
        
        # First, check for tasks that are already assigned but the agent is not working
        for task_id in self.task_queue.in_progress_tasks:
            task = memory_store.tasks.get(task_id)
            if task and task.agent_id:
                agent = memory_store.agents.get(task.agent_id)
                if agent and agent.status != AgentStatus.WORKING:
                    # Agent is not working on this task, make it available
                    if agent.agent_type == "manager":
                        manager_tasks.append(task)
                    else:
                        available_tasks.append(task)
                    logger.info(f"🔄 Task {task_id} reassigned - agent {agent.name} not working")
        
        # Then check pending tasks
        for task_id in self.task_queue.pending_tasks:
            task = memory_store.tasks.get(task_id)
            if task:
                # Check if task is unassigned or assigned to a non-existent agent
                if not task.agent_id or task.agent_id not in memory_store.agents:
                    # Separate manager tasks from worker tasks
                    if "PLANNING" in task.description.upper() or "REVIEW" in task.description.upper() or "FOLLOW-UP" in task.description.upper():
                        manager_tasks.append(task)
                    else:
                        available_tasks.append(task)
                # Also check if task has satisfied dependencies
                elif self._are_dependencies_satisfied(task_id):
                    if "PLANNING" in task.description.upper() or "REVIEW" in task.description.upper() or "FOLLOW-UP" in task.description.upper():
                        manager_tasks.append(task)
                    else:
                        available_tasks.append(task)
        
        # If we have idle workers but no available tasks, force assign any pending tasks
        if not available_tasks and idle_workers and self.task_queue.pending_tasks:
            logger.warning(f"⚠️ {len(idle_workers)} idle workers but no available tasks - forcing assignment")
            for task_id in self.task_queue.pending_tasks:
                task = memory_store.tasks.get(task_id)
                if task and "PLANNING" not in task.description.upper() and "REVIEW" not in task.description.upper():
                    available_tasks.append(task)
                    logger.info(f"🔄 Force-assigning worker task: {task.description[:50]}...")
        
        # Assign manager tasks first (planning and reviews)
        if idle_manager and manager_tasks:
            logger.info(f"👨‍💼 Assigning {len(manager_tasks)} manager tasks to {idle_manager.name}")
            for task in manager_tasks:
                task.agent_id = idle_manager.id
                idle_manager.status = AgentStatus.WORKING
                idle_manager.current_task_id = task.id
                idle_manager.last_activity = datetime.now()
                
                # Move task to in_progress
                if task.id in self.task_queue.pending_tasks:
                    self.task_queue.pending_tasks.remove(task.id)
                if task.id not in self.task_queue.in_progress_tasks:
                    self.task_queue.in_progress_tasks.add(task.id)
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()
                
                logger.info(f"👨‍💼 Assigned manager task '{task.description[:50]}...' to {idle_manager.name}")
        
        # Assign worker tasks
        if available_tasks:
            logger.info(f"🤖 Assigning {len(available_tasks)} available tasks to {len(idle_workers)} idle workers")
            
            # Assign tasks to idle workers (round-robin)
            for i, task in enumerate(available_tasks):
                worker = idle_workers[i % len(idle_workers)]
                task.agent_id = worker.id
                logger.info(f"🤖 Assigned task '{task.description[:50]}...' to {worker.name}")
                
                # Mark worker as working
                worker.status = AgentStatus.WORKING
                worker.current_task_id = task.id
                worker.last_activity = datetime.now()
                
                # Move task to in_progress if it's not already there
                if task.id in self.task_queue.pending_tasks:
                    self.task_queue.pending_tasks.remove(task.id)
                if task.id not in self.task_queue.in_progress_tasks:
                    self.task_queue.in_progress_tasks.add(task.id)
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()
        
        if not available_tasks and not manager_tasks:
            logger.debug("⏸️ No available tasks for idle workers or manager")
        else:
            logger.info(f"✅ Assigned {len(available_tasks)} worker tasks and {len(manager_tasks)} manager tasks")

    def _auto_assign_unassigned_tasks(self):
        """Auto-assign unassigned tasks to available workers"""
        # Get all available worker agents
        available_workers = [
            agent for agent in memory_store.agents.values() 
            if agent.agent_type == "worker" and agent.is_active and agent.status == AgentStatus.IDLE
        ]
        
        if not available_workers:
            logger.debug("⏸️ No available workers for auto-assignment")
            return
        
        # Get unassigned tasks (tasks without an agent_id or with non-existent agent)
        unassigned_tasks = []
        for task_id in self.task_queue.pending_tasks:
            task = memory_store.tasks.get(task_id)
            if task and (not task.agent_id or task.agent_id not in memory_store.agents):
                unassigned_tasks.append(task)
        
        if not unassigned_tasks:
            logger.debug("⏸️ No unassigned tasks to auto-assign")
            return
        
        logger.info(f"🤖 Auto-assigning {len(unassigned_tasks)} unassigned tasks to {len(available_workers)} available workers")
        
        # Round-robin assignment to available workers
        for i, task in enumerate(unassigned_tasks):
            worker = available_workers[i % len(available_workers)]
            task.agent_id = worker.id
            logger.info(f"🤖 Assigned task '{task.description[:50]}...' to {worker.name}")
            
            # Mark worker as busy
            worker.status = AgentStatus.WORKING
            worker.current_task_id = task.id
            worker.last_activity = datetime.now()

    def _scavenge_unassigned_tasks(self):
        """Aggressively find and assign any unassigned tasks to idle workers"""
        # Get idle workers
        idle_workers = [
            agent for agent in memory_store.agents.values() 
            if agent.agent_type == "worker" and agent.is_active and agent.status == AgentStatus.IDLE
        ]
        
        # Get idle manager
        idle_manager = next(
            (agent for agent in memory_store.agents.values() 
             if agent.agent_type == "manager" and agent.is_active and agent.status == AgentStatus.IDLE), 
            None
        )
        
        if not idle_workers and not idle_manager:
            return
        
        # Find all unassigned or orphaned tasks
        unassigned_tasks = []
        manager_tasks = []
        
        # Check pending tasks
        for task_id in self.task_queue.pending_tasks:
            task = memory_store.tasks.get(task_id)
            if task and (not task.agent_id or task.agent_id not in memory_store.agents):
                if self._are_dependencies_satisfied(task_id):
                    # Determine if task should go to manager or workers
                    if self._should_task_go_to_manager(task):
                        manager_tasks.append(task)
                    else:
                        unassigned_tasks.append(task)
        
        # Check in-progress tasks that might be orphaned
        for task_id in self.task_queue.in_progress_tasks:
            task = memory_store.tasks.get(task_id)
            if task and task.agent_id:
                agent = memory_store.agents.get(task.agent_id)
                if not agent or agent.status != AgentStatus.WORKING:
                    # Task is assigned but agent is not working, reassign
                    if self._should_task_go_to_manager(task):
                        manager_tasks.append(task)
                    else:
                        unassigned_tasks.append(task)
                    logger.info(f"🔄 Found orphaned task: {task.description[:50]}...")
        
        # If we have idle workers but no unassigned tasks, force assign ANY pending tasks
        if not unassigned_tasks and not manager_tasks and (idle_workers or idle_manager) and self.task_queue.pending_tasks:
            logger.warning(f"⚠️ Idle agents but no unassigned tasks - force scavenging")
            for task_id in self.task_queue.pending_tasks:
                task = memory_store.tasks.get(task_id)
                if task:
                    if self._should_task_go_to_manager(task):
                        manager_tasks.append(task)
                    else:
                        unassigned_tasks.append(task)
                    logger.info(f"🔄 Force-scavenging task: {task.description[:50]}...")
        
        # Assign manager tasks first
        if idle_manager and manager_tasks:
            logger.info(f"👨‍💼 Scavenging {len(manager_tasks)} manager tasks to {idle_manager.name}")
            for task in manager_tasks:
                task.agent_id = idle_manager.id
                idle_manager.status = AgentStatus.WORKING
                idle_manager.current_task_id = task.id
                idle_manager.last_activity = datetime.now()
                
                # Ensure task is in in_progress
                if task.id in self.task_queue.pending_tasks:
                    self.task_queue.pending_tasks.remove(task.id)
                if task.id not in self.task_queue.in_progress_tasks:
                    self.task_queue.in_progress_tasks.add(task.id)
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()
                
                logger.info(f"👨‍💼 Scavenged manager task '{task.description[:50]}...' to {idle_manager.name}")
        
        # Assign worker tasks
        if unassigned_tasks:
            logger.info(f"🔍 Found {len(unassigned_tasks)} unassigned/orphaned worker tasks")
            
            # Assign tasks to idle workers (round-robin)
            for i, task in enumerate(unassigned_tasks):
                worker = idle_workers[i % len(idle_workers)]
                task.agent_id = worker.id
                logger.info(f"🤖 Scavenged task '{task.description[:50]}...' to {worker.name}")
                
                # Mark worker as working
                worker.status = AgentStatus.WORKING
                worker.current_task_id = task.id
                worker.last_activity = datetime.now()
                
                # Ensure task is in in_progress
                if task.id in self.task_queue.pending_tasks:
                    self.task_queue.pending_tasks.remove(task.id)
                if task.id not in self.task_queue.in_progress_tasks:
                    self.task_queue.in_progress_tasks.add(task.id)
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()

    def _create_retry_task(self, agent: Agent, original_task: Task, response: str):
        """Create a retry task when the original task was incomplete"""
        retry_task = Task(
            id=str(uuid.uuid4()),
            description=f"""RETRY TASK - IMPROVED APPROACH

Original Task: {original_task.description}

Previous Response: {response[:500]}...

The previous attempt was incomplete. Please:
1. Analyze what was missing from the previous response
2. Provide a complete and improved solution
3. Ensure all requirements are met
4. Create any necessary files
5. End with "TASK COMPLETED"

This is a retry attempt - make sure to complete the task properly this time.""",
            agent_id=agent.id,
            priority=original_task.priority + 1,  # Higher priority for retry
            dependencies=original_task.dependencies
        )
        
        self.task_queue.add_task(retry_task)
        logger.info(f"🔄 Created retry task for {agent.name}: {retry_task.description[:50]}...")

    async def _create_tasks_from_response(self, agent: Agent, response: str):
        """Create new tasks from any API response"""
        try:
            # For manager responses, always try to extract task assignments
            if agent.agent_type == "manager":
                await self._handle_manager_response(agent, response)
            else:
                # For worker responses, check if they suggest new tasks
                if "create task" in response.lower() or "next task" in response.lower() or "additional work" in response.lower():
                    logger.info(f"🔍 Worker {agent.name} suggested new tasks, creating follow-up task...")
                    
                    # Create a follow-up task for the manager to review
                    follow_up_task = Task(
                        id=str(uuid.uuid4()),
                        description=f"""FOLLOW-UP TASK CREATION

Worker {agent.name} completed their task and suggested additional work:

WORKER RESPONSE: {response[:300]}...

Please review this response and create any additional tasks that might be needed.
Consider if the work is complete or if more tasks are required.""",
                        agent_id=next((a.id for a in memory_store.agents.values() if a.agent_type == "manager"), None),
                        priority=5
                    )
                    
                    if follow_up_task.agent_id:
                        self.task_queue.add_task(follow_up_task)
                        logger.info(f"📋 Created follow-up task for manager based on {agent.name}'s response")
                        
        except Exception as e:
            logger.error(f"❌ Error creating tasks from response: {e}")

    def _immediately_assign_next_task(self, worker: Agent):
        """Immediately assign the next available task to a worker who just completed one"""
        # Find any available task
        available_task = None
        
        # First, check for tasks with satisfied dependencies
        for task_id in self.task_queue.pending_tasks:
            task = memory_store.tasks.get(task_id)
            if task and self._are_dependencies_satisfied(task_id):
                if not task.agent_id or task.agent_id not in memory_store.agents:
                    available_task = task
                    break
        
        # If no tasks with satisfied dependencies, force assign any pending task
        if not available_task and self.task_queue.pending_tasks:
            task_id = self.task_queue.pending_tasks[0]
            available_task = memory_store.tasks.get(task_id)
            logger.warning(f"🚨 Force assigning task to {worker.name} without dependency check")
        
        if available_task:
            available_task.agent_id = worker.id
            worker.status = AgentStatus.WORKING
            worker.current_task_id = available_task.id
            worker.last_activity = datetime.now()
            
            # Move task to in_progress
            if available_task.id in self.task_queue.pending_tasks:
                self.task_queue.pending_tasks.remove(available_task.id)
            if available_task.id not in self.task_queue.in_progress_tasks:
                self.task_queue.in_progress_tasks.add(available_task.id)
            available_task.status = TaskStatus.IN_PROGRESS
            available_task.started_at = datetime.now()
            
            logger.info(f"⚡ Immediately assigned next task to {worker.name}: {available_task.description[:50]}...")
        else:
            logger.info(f"✅ No more tasks available for {worker.name}")

    def _force_assign_to_idle_workers(self):
        """Force assign any remaining tasks to idle workers - this is the final fallback"""
        # Get idle workers
        idle_workers = [
            agent for agent in memory_store.agents.values() 
            if agent.agent_type == "worker" and agent.is_active and agent.status == AgentStatus.IDLE
        ]
        
        if not idle_workers:
            return
        
        # If there are any pending tasks and idle workers, force assign them
        if self.task_queue.pending_tasks:
            logger.warning(f"🚨 {len(idle_workers)} idle workers with {len(self.task_queue.pending_tasks)} pending tasks - FORCE ASSIGNING")
            
            # Get all pending tasks
            pending_tasks = []
            for task_id in self.task_queue.pending_tasks:
                task = memory_store.tasks.get(task_id)
                if task:
                    pending_tasks.append(task)
            
            # Force assign tasks to idle workers
            for i, task in enumerate(pending_tasks):
                worker = idle_workers[i % len(idle_workers)]
                task.agent_id = worker.id
                logger.warning(f"🚨 FORCE ASSIGNED task '{task.description[:50]}...' to {worker.name}")
                
                # Mark worker as working
                worker.status = AgentStatus.WORKING
                worker.current_task_id = task.id
                worker.last_activity = datetime.now()
                
                # Move task to in_progress
                if task.id in self.task_queue.pending_tasks:
                    self.task_queue.pending_tasks.remove(task.id)
                if task.id not in self.task_queue.in_progress_tasks:
                    self.task_queue.in_progress_tasks.add(task.id)
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()

    def _should_task_go_to_manager(self, task: Task) -> bool:
        """Determine if a task should be assigned to the manager or workers"""
        description_upper = task.description.upper()
        
        # Manager keywords - tasks that should go to manager
        manager_keywords = [
            "PLANNING", "REVIEW", "FOLLOW-UP", "ARCHITECTURE", "DESIGN",
            "PROJECT PLAN", "TASK BREAKDOWN", "ASSIGNMENT", "COORDINATION",
            "MANAGEMENT", "LEADERSHIP", "STRATEGY", "ANALYSIS", "EVALUATION",
            "ASSESSMENT", "APPROVAL", "VALIDATION", "VERIFICATION", "CHECK",
            "INSPECTION", "AUDIT", "COMPLIANCE", "STANDARDS", "QUALITY",
            "TESTING PLAN", "DEPLOYMENT PLAN", "INTEGRATION PLAN",
            "DOCUMENTATION PLAN", "SECURITY REVIEW", "PERFORMANCE REVIEW"
        ]
        
        # Worker keywords - tasks that should go to workers
        worker_keywords = [
            "IMPLEMENT", "CODE", "DEVELOP", "BUILD", "CREATE", "WRITE",
            "PROGRAM", "SCRIPT", "CONFIGURE", "SETUP", "INSTALL", "DEPLOY",
            "TEST", "DEBUG", "FIX", "OPTIMIZE", "REFACTOR", "UPDATE",
            "MAINTAIN", "SUPPORT", "MONITOR", "BACKUP", "RESTORE",
            "FRONTEND", "BACKEND", "API", "DATABASE", "UI", "UX",
            "COMPONENT", "MODULE", "SERVICE", "FUNCTION", "CLASS",
            "FILE", "DIRECTORY", "STRUCTURE", "TEMPLATE", "STYLE",
            "DOCKER", "CONTAINER", "PIPELINE", "CI/CD", "INFRASTRUCTURE"
        ]
        
        # Check for manager keywords first
        for keyword in manager_keywords:
            if keyword in description_upper:
                logger.debug(f"📋 Task assigned to manager due to keyword: {keyword}")
                return True
        
        # Check for worker keywords
        for keyword in worker_keywords:
            if keyword in description_upper:
                logger.debug(f"📋 Task assigned to worker due to keyword: {keyword}")
                return False
        
        # Default decision based on task length and complexity
        # Shorter, simpler tasks go to workers; longer, complex tasks go to manager
        if len(task.description) < 200:
            logger.debug(f"📋 Task assigned to worker (short task)")
            return False
        else:
            logger.debug(f"📋 Task assigned to manager (complex task)")
            return True

    def _auto_assign_task_by_description(self, description: str) -> Optional[Agent]:
        """Auto-assign task to agent based on description keywords"""
        # Get available workers
        available_workers = [
            agent for agent in memory_store.agents.values() 
            if agent.agent_type == "worker" and agent.is_active and agent.status == AgentStatus.IDLE
        ]
        
        if not available_workers:
            return None
        
        # Simple round-robin assignment for generalist workers
        # Find the worker with the least tasks completed
        worker = min(available_workers, key=lambda w: w.performance_metrics.get('tasks_completed', 0))
        logger.info(f"🤖 Auto-assigning to worker: {worker.name}")
        return worker

    def _is_task_complete(self, response: str) -> bool:
        """Check if task is completed"""
        completion_indicators = [
            "task completed",
            "task finished", 
            "implementation complete",
            "work completed",
            "finished successfully",
            "planning complete",
            "architecture complete",
            "project plan complete",
            "task breakdown complete",
            "assignments complete",
            "done",
            "complete",
            "finished",
            "ready",
            "implemented",
            "created",
            "built",
            "developed",
            "configured",
            "set up",
            "established"
        ]
        
        response_lower = response.lower()
        return any(indicator in response_lower for indicator in completion_indicators)

    def _process_stuck_tasks(self):
        """Process tasks that might be stuck in in_progress state"""
        current_time = datetime.now()
        stuck_tasks = []
        
        for task_id in list(self.task_queue.in_progress_tasks):
            task = memory_store.tasks.get(task_id)
            if task and task.started_at:
                elapsed = (current_time - task.started_at).total_seconds()
                if elapsed > 30:  # 30 seconds timeout for scavenging
                    stuck_tasks.append(task_id)
                    logger.warning(f"⏰ Task {task_id} stuck for {elapsed:.1f}s, may need scavenging")
        
        # Only force complete tasks that are really stuck (5+ minutes)
        really_stuck_tasks = []
        for task_id in stuck_tasks:
            task = memory_store.tasks.get(task_id)
            if task and task.started_at:
                elapsed = (current_time - task.started_at).total_seconds()
                if elapsed > 300:  # 5 minutes absolute timeout
                    really_stuck_tasks.append(task_id)
                    logger.warning(f"⏰ Task {task_id} really stuck for {elapsed:.1f}s, forcing completion")
        
        # Force complete really stuck tasks
        for task_id in really_stuck_tasks:
            self.task_queue.complete_task(task_id, "Task completed due to timeout", [])
            # Reset the agent
            task = memory_store.tasks.get(task_id)
            if task and task.agent_id:
                agent = memory_store.agents.get(task.agent_id)
                if agent:
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
                    logger.info(f"🔄 Reset agent {agent.name} to IDLE after really stuck task")

    def _check_for_stuck_agents(self):
        """Check for agents that have been working too long and reset them"""
        current_time = datetime.now()
        for agent in memory_store.agents.values():
            if agent.status == AgentStatus.WORKING and agent.current_task_id:
                # Check if agent has been working for more than 10 minutes
                elapsed = (current_time - agent.last_activity).total_seconds()
                if elapsed > 600:  # 10 minutes
                    logger.warning(f"🔄 Agent {agent.name} has been working for {elapsed:.1f}s, resetting...")
                    agent.status = AgentStatus.IDLE
                    agent.current_task_id = None
                    
                    # Move the task back to pending
                    if agent.current_task_id in self.task_queue.in_progress_tasks:
                        self.task_queue.in_progress_tasks.remove(agent.current_task_id)
                        self.task_queue.pending_tasks.append(agent.current_task_id)
                        task = memory_store.tasks.get(agent.current_task_id)
                        if task:
                            task.status = TaskStatus.PENDING
                            task.started_at = None
                            task.agent_id = None  # Clear assignment so it can be reassigned

    def _check_project_completion(self):
        """Check if all tasks are completed and trigger final review"""
        task_status = self.task_queue.get_status()
        total_tasks = task_status['pending'] + task_status['in_progress'] + task_status['completed'] + task_status['failed']
        
        # Check if any workers are still working
        working_workers = [
            agent for agent in memory_store.agents.values()
            if agent.agent_type == "worker" and agent.status == AgentStatus.WORKING
        ]
        
        # Check if manager is working
        manager_working = any(
            agent.status == AgentStatus.WORKING 
            for agent in memory_store.agents.values() 
            if agent.agent_type == "manager"
        )
        
        logger.info(f"🔍 Project completion check - Tasks: {task_status}, Working workers: {len(working_workers)}, Manager working: {manager_working}")
        
        # Only proceed if we have tasks and no pending/in-progress tasks AND no workers are working
        if (total_tasks > 0 and 
            task_status['pending'] == 0 and 
            task_status['in_progress'] == 0 and 
            len(working_workers) == 0 and
            not manager_working):
            
            logger.info(f"🎯 All tasks completed and no workers are working! Status: {task_status}")
            
            # Check if we need final review
            if not hasattr(self, '_final_review_triggered'):
                self._final_review_triggered = False
            
            if not self._final_review_triggered:
                self._trigger_final_review()
                self._final_review_triggered = True
                
                # Set a timeout for the final review (5 minutes)
                if not hasattr(self, '_final_review_start_time'):
                    self._final_review_start_time = time.time()
            
            # Check if final review is taking too long (5 minutes timeout)
            elif hasattr(self, '_final_review_start_time'):
                elapsed = time.time() - self._final_review_start_time
                if elapsed > 300:  # 5 minutes
                    logger.warning(f"⏰ Final review taking too long ({elapsed:.1f}s), forcing completion")
                    self._mark_project_ready_for_completion()
                    self._final_review_triggered = False  # Reset for next time
        else:
            # Reset final review trigger if there are still pending tasks or working workers
            if hasattr(self, '_final_review_triggered') and self._final_review_triggered:
                logger.info("🔄 Resetting final review trigger - tasks or workers still active")
                self._final_review_triggered = False

    def _trigger_final_review(self):
        """Trigger final review by manager"""
        try:
            # Find the manager agent
            manager = next((agent for agent in memory_store.agents.values() if agent.agent_type == "manager"), None)
            if not manager:
                logger.error("❌ No manager agent found for final review")
                return
            
            # Create final review task
            review_task = Task(
                id=str(uuid.uuid4()),
                description=f"""FINAL PROJECT REVIEW AND COMPLETION

All team tasks have been completed. Your job is to:

1. Review all completed tasks and their outputs
2. Verify that all required files have been created
3. Check that the project meets the original requirements
4. Ensure code quality and best practices
5. Provide a final summary of the project

PROJECT REQUIREMENTS: {self.current_project}

COMPLETED TASKS:
{self._get_completed_tasks_summary()}

PROJECT FILES:
{self._get_project_files_summary()}

Please review everything and provide:
- A summary of what was accomplished
- Any quality issues found
- Recommendations for improvements
- Final project status

End your review with "PROJECT COMPLETED" when satisfied.""",
                agent_id=manager.id,
                priority=10
            )
            
            self.task_queue.add_task(review_task)
            logger.info(f"👨‍💼 Triggered final review task for {manager.name}")
            
        except Exception as e:
            logger.error(f"❌ Error triggering final review: {e}")

    def _get_completed_tasks_summary(self) -> str:
        """Get summary of completed tasks"""
        summary = []
        for task_id in self.task_queue.completed_tasks:
            task = memory_store.tasks.get(task_id)
            if task:
                agent = memory_store.agents.get(task.agent_id)
                agent_name = agent.name if agent else "Unknown"
                summary.append(f"- {agent_name}: {task.description[:100]}...")
        
        return "\n".join(summary) if summary else "No completed tasks found"

    def _get_project_files_summary(self) -> str:
        """Get summary of project files"""
        current_project = next((p for p in memory_store.projects.values() if p.status == "running"), None)
        if not current_project or not current_project.files:
            return "No files created yet"
        
        files_summary = []
        for filename in current_project.files.keys():
            files_summary.append(f"- {filename}")
        
        return f"Total files: {len(current_project.files)}\n" + "\n".join(files_summary)

    def _mark_project_ready_for_completion(self):
        """Mark project as ready for completion after final review"""
        try:
            # Find the running project
            current_project = next((p for p in memory_store.projects.values() if p.status == "running"), None)
            if current_project:
                current_project.status = "reviewed"
                logger.info(f"✅ Project {current_project.id} marked as reviewed and ready for completion")
                
                # Emit project completion event
                socketio.emit('project_reviewed', {
                    'project_id': current_project.id,
                    'files_count': len(current_project.files),
                    'files': list(current_project.files.keys())
                })
                
                logger.info(f"🎉 Project is ready for download! Files created: {list(current_project.files.keys())}")
            else:
                logger.warning("⚠️ No running project found to mark as reviewed")
                
        except Exception as e:
            logger.error(f"❌ Error marking project as ready: {e}")

    def _clean_and_validate_response(self, response: str) -> str:
        """Clean and validate response data to handle formatting inconsistencies"""
        if not response:
            return ""
        
        # Remove extra whitespace and normalize line endings
        cleaned = response.strip()
        cleaned = re.sub(r'\r\n', '\n', cleaned)  # Normalize line endings
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)  # Remove extra blank lines
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)  # Normalize spaces
        
        # Clean up common formatting issues
        cleaned = re.sub(r'```\s*json\s*', '```json\n', cleaned)  # Fix JSON code blocks
        cleaned = re.sub(r'```\s*\n', '```\n', cleaned)  # Fix code block endings
        cleaned = re.sub(r'\n\s*```', '\n```', cleaned)  # Fix code block starts
        
        # Handle common JSON formatting issues
        cleaned = re.sub(r',\s*}', '}', cleaned)  # Remove trailing commas
        cleaned = re.sub(r',\s*]', ']', cleaned)  # Remove trailing commas in arrays
        cleaned = re.sub(r'(["\w])\s*:\s*(["\w])', r'\1": "\2', cleaned)  # Fix missing quotes
        
        return cleaned

    def _extract_and_clean_json(self, response: str) -> Optional[Dict]:
        """Extract and clean JSON data from response with robust error handling"""
        try:
            # Clean the response first
            cleaned_response = self._clean_and_validate_response(response)
            
            # Try multiple JSON extraction patterns
            json_patterns = [
                r'```json\s*\n(.*?)\n```',
                r'```\s*\n(.*?)\n```',  # Fallback for any code block
                r'\{.*?"tasks".*?\}',  # Simple JSON with tasks
                r'\{[^{}]*"tasks"[^{}]*\}',  # More flexible JSON pattern
            ]
            
            for pattern_idx, pattern in enumerate(json_patterns):
                json_match = re.search(pattern, cleaned_response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1) if len(json_match.groups()) > 0 else json_match.group(0)
                    
                    # Clean the extracted JSON string
                    json_str = self._clean_and_validate_response(json_str)
                    
                    try:
                        task_data = json.loads(json_str)
                        logger.info(f"✅ Found JSON task data with pattern {pattern_idx + 1}")
                        return task_data
                    except json.JSONDecodeError as e:
                        logger.debug(f"❌ JSON decode failed for pattern {pattern_idx + 1}: {e}")
                        logger.debug(f"📝 Attempted JSON: {json_str[:200]}...")
                        
                        # Try to fix common JSON issues
                        fixed_json = self._fix_common_json_issues(json_str)
                        if fixed_json:
                            try:
                                task_data = json.loads(fixed_json)
                                logger.info(f"✅ Fixed JSON and parsed successfully")
                                return task_data
                            except json.JSONDecodeError:
                                logger.debug(f"❌ Fixed JSON still failed to parse")
                                continue
            
            logger.warning("⚠️ No valid JSON task data found in manager response")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extracting JSON: {e}")
            return None

    def _fix_common_json_issues(self, json_str: str) -> Optional[str]:
        """Fix common JSON formatting issues"""
        try:
            # Fix missing quotes around property names
            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
            
            # Fix missing quotes around string values
            json_str = re.sub(r':\s*([a-zA-Z][a-zA-Z0-9_]*)\s*([,}])', r': "\1"\2', json_str)
            
            # Fix trailing commas
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            
            # Fix missing commas
            json_str = re.sub(r'"\s*}\s*"', '",\n  "', json_str)
            
            # Fix unescaped quotes in strings
            json_str = re.sub(r'([^\\])"([^"]*?)([^\\])"', r'\1"\2\3"', json_str)
            
            return json_str
        except Exception as e:
            logger.debug(f"❌ Error fixing JSON: {e}")
            return None

    def _clean_and_validate_task_info(self, task_info: Dict) -> Optional[Dict]:
        """Clean and validate task information"""
        try:
            cleaned_task = {}
            
            # Clean and validate agent field
            agent = task_info.get("agent", "")
            if agent:
                cleaned_task["agent"] = self._clean_agent_name(str(agent))
            else:
                logger.warning("⚠️ Task missing 'agent' field")
                return None
            
            # Clean and validate description field
            description = task_info.get("description", "")
            if description:
                cleaned_task["description"] = self._clean_description(str(description))
            else:
                logger.warning("⚠️ Task missing 'description' field")
                return None
            
            # Clean and validate priority field
            priority = task_info.get("priority", 5)
            try:
                priority = int(priority)
                if priority < 1:
                    priority = 1
                elif priority > 10:
                    priority = 10
                cleaned_task["priority"] = priority
            except (ValueError, TypeError):
                logger.warning("⚠️ Invalid priority value, using default 5")
                cleaned_task["priority"] = 5
            
            # Clean and validate dependencies field
            dependencies = task_info.get("dependencies", [])
            if isinstance(dependencies, list):
                cleaned_task["dependencies"] = [str(dep).strip() for dep in dependencies if dep]
            else:
                cleaned_task["dependencies"] = []
            
            # Clean and validate files_expected field
            files_expected = task_info.get("files_expected", [])
            if isinstance(files_expected, list):
                cleaned_task["files_expected"] = [str(f).strip() for f in files_expected if f]
            else:
                cleaned_task["files_expected"] = []
            
            return cleaned_task
            
        except Exception as e:
            logger.error(f"❌ Error cleaning task info: {e}")
            return None

    def _clean_agent_name(self, agent_name: str) -> str:
        """Clean and normalize agent names"""
        if not agent_name:
            return ""
        
        # Remove extra whitespace and normalize
        cleaned = agent_name.strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)  # Normalize spaces
        
        # Handle common variations
        cleaned = cleaned.replace("developer", "Developer")
        cleaned = cleaned.replace("dev", "Developer")
        cleaned = cleaned.replace("worker", "Developer")
        
        # Ensure proper formatting
        if cleaned.lower() in ["developer1", "dev1", "worker1"]:
            return "Developer1"
        elif cleaned.lower() in ["developer2", "dev2", "worker2"]:
            return "Developer2"
        elif cleaned.lower() in ["developer3", "dev3", "worker3"]:
            return "Developer3"
        
        return cleaned

    def _clean_description(self, description: str) -> str:
        """Clean and validate task description"""
        if not description:
            return ""
        
        # Remove extra whitespace and normalize
        cleaned = description.strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)  # Normalize spaces
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)  # Remove extra blank lines
        
        # Ensure minimum length
        if len(cleaned) < 10:
            logger.warning("⚠️ Task description too short")
            return ""
        
        return cleaned

    def _validate_task_and_agent(self, agent: Agent, task: Task) -> bool:
        """Validate task and agent data before processing"""
        try:
            # Validate agent
            if not agent or not agent.id or not agent.name:
                logger.error("❌ Invalid agent data")
                return False
            
            # Validate task
            if not task or not task.id or not task.description:
                logger.error("❌ Invalid task data")
                return False
            
            # Check if agent is active
            if not agent.is_active:
                logger.warning(f"⚠️ Agent {agent.name} is not active")
                return False
            
            # Check if task is in valid state
            if task.status not in [TaskStatus.PENDING, TaskStatus.IN_PROGRESS]:
                logger.warning(f"⚠️ Task {task.id} is in invalid state: {task.status}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error validating task and agent: {e}")
            return False

    def _clean_and_validate_filename(self, filename: str) -> Optional[str]:
        """Clean and validate filename"""
        if not filename:
            return None
        
        # Remove extra whitespace and normalize
        cleaned = filename.strip()
        cleaned = re.sub(r'\s+', '', cleaned)  # Remove all spaces
        
        # Remove invalid characters
        cleaned = re.sub(r'[<>:"/\\|?*]', '_', cleaned)
        
        # Ensure it has a valid extension
        if '.' not in cleaned:
            logger.warning(f"⚠️ Filename missing extension: {filename}")
            return None
        
        # Check for minimum length
        if len(cleaned) < 3:
            logger.warning(f"⚠️ Filename too short: {filename}")
            return None
        
        return cleaned

    def _clean_and_validate_file_content(self, content: str) -> Optional[str]:
        """Clean and validate file content"""
        if not content:
            return None
        
        # Remove null bytes and other problematic characters
        cleaned = content.replace('\x00', '')
        cleaned = re.sub(r'[\x01-\x08\x0B\x0C\x0E-\x1F\x7F]', '', cleaned)
        
        # Normalize line endings
        cleaned = re.sub(r'\r\n', '\n', cleaned)
        cleaned = re.sub(r'\r', '\n', cleaned)
        
        # Remove trailing whitespace
        cleaned = re.sub(r'[ \t]+$', '', cleaned, flags=re.MULTILINE)
        
        # Ensure minimum content
        if len(cleaned.strip()) < 1:
            logger.warning("⚠️ File content too short")
            return None
        
        return cleaned

    async def _handle_manager_response(self, manager: Agent, response: str):
        """Handle manager task assignments"""
        try:
            logger.info(f"🔍 Processing manager response for task creation...")
            logger.debug(f"📝 Manager response: {response[:500]}...")
            
            # Extract and clean JSON data
            task_data = self._extract_and_clean_json(response)
            
            if not task_data:
                logger.warning("⚠️ No valid JSON task data found in manager response")
                logger.debug(f"📝 Full response: {response}")
                return
            
            if "tasks" in task_data:
                tasks_created = 0
                worker_tasks = []
                review_tasks = []
                
                # Validate and clean task data
                tasks_list = task_data["tasks"]
                if not isinstance(tasks_list, list):
                    logger.error("❌ 'tasks' is not a list in JSON data")
                    return
                
                for task_info in tasks_list:
                    # Validate task_info is a dictionary
                    if not isinstance(task_info, dict):
                        logger.warning(f"⚠️ Skipping invalid task info: {task_info}")
                        continue
                    
                    # Clean and validate task data
                    cleaned_task_info = self._clean_and_validate_task_info(task_info)
                    if not cleaned_task_info:
                        logger.warning(f"⚠️ Skipping invalid task after cleaning")
                        continue
                    
                    # Find target agent
                    target_agent = None
                    agent_name = cleaned_task_info.get("agent", "")
                    agent_role = cleaned_task_info.get("agent", "")
                    
                    # Clean agent name/role
                    agent_name = self._clean_agent_name(agent_name)
                    agent_role = self._clean_agent_name(agent_role)
                    
                    logger.debug(f"🔍 Looking for agent: '{agent_name}' or role: '{agent_role}'")
                    
                    for agent in memory_store.agents.values():
                        # Try multiple matching strategies
                        agent_name_lower = agent_name.lower().strip()
                        agent_role_lower = agent_role.lower().strip()
                        agent_actual_name_lower = agent.name.lower().strip()
                        agent_actual_role_lower = agent.role.lower().strip()
                        
                        # Direct name match
                        if agent_actual_name_lower == agent_name_lower:
                            target_agent = agent
                            logger.info(f"✅ Found target agent by name: {agent.name}")
                            break
                        
                        # Role match
                        elif agent_actual_role_lower == agent_role_lower:
                            target_agent = agent
                            logger.info(f"✅ Found target agent by role: {agent.name} ({agent.role})")
                            break
                        
                        # Partial role matching
                        elif (agent_actual_role_lower in agent_name_lower or 
                              agent_name_lower in agent_actual_role_lower):
                            target_agent = agent
                            logger.info(f"✅ Found target agent by partial role match: {agent.name} ({agent.role})")
                            break
                        
                        # Handle common variations for generalist workers
                        elif (agent_name_lower in ["developer1", "dev1", "worker1"] and 
                              agent_actual_role_lower == "full stack developer"):
                            target_agent = agent
                            logger.info(f"✅ Found developer 1: {agent.name}")
                            break
                        elif (agent_name_lower in ["developer2", "dev2", "worker2"] and 
                              agent_actual_role_lower == "full stack developer"):
                            target_agent = agent
                            logger.info(f"✅ Found developer 2: {agent.name}")
                            break
                        elif (agent_name_lower in ["developer3", "dev3", "worker3"] and 
                              agent_actual_role_lower == "full stack developer"):
                            target_agent = agent
                            logger.info(f"✅ Found developer 3: {agent.name}")
                            break
                    
                    if target_agent:
                        # Create worker task
                        worker_task = Task(
                            id=str(uuid.uuid4()),
                            description=task_info.get("description", ""),
                            agent_id=target_agent.id,
                            priority=task_info.get("priority", 5),
                            dependencies=task_info.get("dependencies", [])
                        )
                        worker_tasks.append(worker_task)
                        
                        # Create corresponding review task for manager
                        review_task = Task(
                            id=str(uuid.uuid4()),
                            description=f"""REVIEW TASK COMPLETION

Review the work completed by {target_agent.name} for the following task:

TASK: {task_info.get("description", "")}

Please:
1. Review the completed work and any files created
2. Check if the task meets the requirements
3. Verify code quality and best practices
4. Mark the task as complete if satisfied

End your review with "TASK COMPLETED" if the work is satisfactory.""",
                            agent_id=manager.id,
                            priority=task_info.get("priority", 5),
                            dependencies=[worker_task.id]  # Review depends on worker task completion
                        )
                        review_tasks.append(review_task)
                        
                        tasks_created += 1
                        
                        # Notify worker
                        await self._send_message(
                            manager.id, 
                            target_agent.id, 
                            f"New task assigned: {worker_task.description[:100]}...", 
                            "task_assignment"
                        )
                        
                        logger.info(f"📋 Worker task assigned to {target_agent.name}: {worker_task.description[:50]}...")
                        logger.info(f"📋 Review task assigned to {manager.name} for {target_agent.name}'s work")
                    else:
                        logger.warning(f"⚠️ Could not find agent for: {agent_name}/{agent_role}")
                        logger.info(f"📝 Available agents:")
                        for a in memory_store.agents.values():
                            logger.info(f"  - {a.name} ({a.role}) - {a.agent_type}")
                        logger.debug(f"🔍 Tried to match: '{agent_name}' / '{agent_role}'")
                        
                        # Try to auto-assign based on task description
                        auto_assigned_agent = self._auto_assign_task_by_description(task_info.get("description", ""))
                        if auto_assigned_agent:
                            # Create worker task
                            worker_task = Task(
                                id=str(uuid.uuid4()),
                                description=task_info.get("description", ""),
                                agent_id=auto_assigned_agent.id,
                                priority=task_info.get("priority", 5),
                                dependencies=task_info.get("dependencies", [])
                            )
                            worker_tasks.append(worker_task)
                            
                            # Create corresponding review task for manager
                            review_task = Task(
                                id=str(uuid.uuid4()),
                                description=f"""REVIEW TASK COMPLETION

Review the work completed by {auto_assigned_agent.name} for the following task:

TASK: {task_info.get("description", "")}

Please:
1. Review the completed work and any files created
2. Check if the task meets the requirements
3. Verify code quality and best practices
4. Mark the task as complete if satisfied

End your review with "TASK COMPLETED" if the work is satisfactory.""",
                                agent_id=manager.id,
                                priority=task_info.get("priority", 5),
                                dependencies=[worker_task.id]  # Review depends on worker task completion
                            )
                            review_tasks.append(review_task)
                            
                            tasks_created += 1
                            
                            await self._send_message(
                                manager.id, 
                                auto_assigned_agent.id, 
                                f"Auto-assigned task: {worker_task.description[:100]}...", 
                                "task_assignment"
                            )
                            
                            logger.info(f"🤖 Auto-assigned worker task to {auto_assigned_agent.name}: {worker_task.description[:50]}...")
                            logger.info(f"🤖 Auto-assigned review task to {manager.name} for {auto_assigned_agent.name}'s work")
                        else:
                            logger.error(f"❌ Could not auto-assign task: {task_info.get('description', '')[:50]}...")
                
                # Add all worker tasks first
                for task in worker_tasks:
                    self.task_queue.add_task(task)
                
                # Add all review tasks
                for task in review_tasks:
                    self.task_queue.add_task(task)
                
                logger.info(f"🎉 Created {tasks_created} worker tasks and {len(review_tasks)} review tasks from manager response")
            else:
                logger.warning("⚠️ No 'tasks' key found in JSON data")
                logger.debug(f"📝 JSON data keys: {list(task_data.keys())}")
                            
        except Exception as e:
            logger.error(f"❌ Error handling manager response: {e}")
            logger.error(f"📝 Response that caused error: {response[:200]}...")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")

    async def _send_message(self, from_agent_id: str, to_agent_id: Optional[str], content: str, msg_type: str = "communication"):
        """Send message between agents - stored in memory"""
        message = {
            'id': str(uuid.uuid4()),
            'from_agent_id': from_agent_id,
            'to_agent_id': to_agent_id,
            'content': content,
            'type': msg_type,
            'timestamp': datetime.now().isoformat()
        }
        
        memory_store.messages.append(message)
        memory_store.system_metrics['messages_sent'] += 1
        
        # Keep only last 100 messages
        if len(memory_store.messages) > 100:
            memory_store.messages = memory_store.messages[-100:]
        
        # Emit message
        socketio.emit('message_sent', message)

    def _emit_status_update(self):
        """Emit status updates to frontend"""
        try:
            # Prepare agent data
            agents_data = {aid: agent.to_dict() for aid, agent in memory_store.agents.items()}
            
            # Prepare task queue status
            task_status = self.task_queue.get_status()
            
            # Calculate metrics
            uptime = time.time() - memory_store.system_metrics['start_time']
            
            # Emit update
            socketio.emit('system_update', {
                'agents': agents_data,
                'messages': memory_store.messages[-10:],  # Last 10 messages
                'task_queue': task_status,
                'system_running': self.system_running,
                'current_project': self.current_project,
                'metrics': {
                    'uptime': int(uptime),
                    'tasks_processed': memory_store.system_metrics['tasks_processed'],
                    'messages_sent': memory_store.system_metrics['messages_sent'],
                    'files_created': memory_store.system_metrics['files_created'],
                    'api_calls': memory_store.system_metrics['api_calls'],
                    'errors': memory_store.system_metrics['errors']
                }
            })
            
        except Exception as e:
            logger.error(f"Error emitting status update: {e}")

    def stop_project(self):
        """Stop the current project"""
        self.system_running = False
        
        # Reset agent states
        for agent in memory_store.agents.values():
            agent.status = AgentStatus.IDLE
            agent.current_task_id = None
        
        # Mark current project as completed
        for project in memory_store.projects.values():
            if project.status in ["running", "reviewed"]:
                # If no files were created, create some basic files
                if not project.files:
                    logger.warning("⚠️ No files were created, creating basic project structure...")
                    self._create_basic_project_structure(project)
                
                project.status = "completed"
                logger.info(f"📁 Project {project.id} completed with {len(project.files)} files")
                if project.files:
                    logger.info(f"📁 Files created: {list(project.files.keys())}")
                else:
                    logger.warning("⚠️ No files were created in this project")
        
        socketio.emit('project_stopped')
        logger.info("Project stopped")

    def get_project_files(self) -> Dict[str, Any]:
        """Get project files from memory"""
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        if not current_project:
            logger.warning("⚠️ No running or reviewed project found for file listing")
            return {"files": []}
        
        files = []
        logger.info(f"📁 Checking project files for project: {current_project.id}")
        logger.info(f"📁 Project status: {current_project.status}")
        logger.info(f"📁 Project files count: {len(current_project.files)}")
        
        for filename, content in current_project.files.items():
            files.append({
                "path": filename,
                "size": len(content.encode('utf-8')),
                "modified": current_project.created_at.timestamp(),
                "lines": len(content.split('\n'))
            })
            logger.debug(f"📁 File: {filename} ({len(content)} chars)")
        
        logger.info(f"📁 Project has {len(files)} files: {[f['path'] for f in files]}")
        return {"files": files}

    def create_project_zip(self) -> Optional[io.BytesIO]:
        """Create ZIP file of current project from memory"""
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        if not current_project or not current_project.files:
            logger.warning("⚠️ No running/reviewed project or no files to create ZIP")
            logger.info(f"📁 Available projects: {[f'{p.id}: {p.status} ({len(p.files)} files)' for p in memory_store.projects.values()]}")
            return None
        
        logger.info(f"📦 Creating ZIP for project {current_project.id} with {len(current_project.files)} files")
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filename, content in current_project.files.items():
                zip_file.writestr(filename, content)
                logger.debug(f"📁 Added to ZIP: {filename} ({len(content)} chars)")
        
        zip_buffer.seek(0)
        logger.info(f"✅ Created ZIP with {len(current_project.files)} files")
        return zip_buffer

    def _process_in_progress_tasks(self):
        """Process any in-progress tasks that are assigned to working agents"""
        for task_id in list(self.task_queue.in_progress_tasks):
            task = memory_store.tasks.get(task_id)
            if task and task.agent_id:
                agent = memory_store.agents.get(task.agent_id)
                if agent and agent.status == AgentStatus.WORKING and agent.current_task_id == task_id:
                    # Agent is working on this task, process it
                    logger.info(f"🎯 Processing in-progress task for {agent.name}: {task.description[:50]}...")
                    
                    # Create a thread to process this task
                    thread = threading.Thread(
                        target=self._process_task_sync,
                        args=(agent, task)
                    )
                    thread.start()
                    thread.join()  # Wait for this task to complete
                    
                    logger.info(f"✅ Completed processing in-progress task for {agent.name}")

    def _force_process_in_progress_tasks(self):
        """Force process any in-progress tasks that are assigned to working agents"""
        for task_id in list(self.task_queue.in_progress_tasks):
            task = memory_store.tasks.get(task_id)
            if task and task.agent_id:
                agent = memory_store.agents.get(task.agent_id)
                if agent and agent.status == AgentStatus.WORKING and agent.current_task_id == task_id:
                    # Agent is working on this task, process it immediately
                    logger.info(f"🎯 Force processing in-progress task for {agent.name}: {task.description[:50]}...")
                    
                    # Process the task directly (not in a thread to avoid conflicts)
                    self._process_task_sync(agent, task)
                    
                    logger.info(f"✅ Completed force processing in-progress task for {agent.name}")

# Initialize system
system = EnhancedMultiAgentSystem()

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/agents', methods=['GET'])
def get_agents():
    try:
        return jsonify({
            'success': True,
            'agents': {aid: agent.to_dict() for aid, agent in memory_store.agents.items()},
            'system_running': system.system_running,
            'current_project': system.current_project,
            'task_queue': system.task_queue.get_status()
        })
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/start', methods=['POST'])
def start_project():
    try:
        data = request.get_json()
        description = data.get('description', '').strip()
        
        if not description:
            return jsonify({'success': False, 'error': 'Project description is required'}), 400
        
        if len(description) < 10:
            return jsonify({'success': False, 'error': 'Project description must be at least 10 characters'}), 400
        
        # Start project asynchronously
        success = executor.submit(
            lambda: asyncio.run(system.start_project(description))
        ).result(timeout=30)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Project started successfully',
                'project': system.current_project
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to start project'}), 500
            
    except Exception as e:
        logger.error(f"Error starting project: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/stop', methods=['POST'])
def stop_project():
    try:
        system.stop_project()
        return jsonify({'success': True, 'message': 'Project stopped'})
    except Exception as e:
        logger.error(f"Error stopping project: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/files', methods=['GET'])
def get_project_files():
    try:
        files_data = system.get_project_files()
        return jsonify({'success': True, **files_data})
    except Exception as e:
        logger.error(f"Error getting project files: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/status', methods=['GET'])
def get_project_status():
    try:
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        task_status = system.task_queue.get_status()
        
        status_data = {
            'success': True,
            'project_status': current_project.status if current_project else None,
            'task_status': task_status,
            'ready_for_completion': system.is_project_ready_for_completion(),
            'files_count': len(current_project.files) if current_project else 0
        }
        
        return jsonify(status_data)
    except Exception as e:
        logger.error(f"Error getting project status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/files/list', methods=['GET'])
def get_project_files_list():
    try:
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        if not current_project:
            return jsonify({'success': True, 'files': []})
        
        files_list = []
        for filename, content in current_project.files.items():
            files_list.append({
                'name': filename,
                'size': len(content.encode('utf-8')),
                'lines': len(content.split('\n')),
                'type': _get_file_type(filename)
            })
        
        # Sort files by type and name
        files_list.sort(key=lambda x: (x['type'], x['name']))
        
        return jsonify({
            'success': True,
            'files': files_list,
            'total_files': len(files_list),
            'total_size': sum(f['size'] for f in files_list)
        })
    except Exception as e:
        logger.error(f"Error getting project files list: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def _get_file_type(filename):
    """Get file type based on extension"""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    if ext in ['py']:
        return 'python'
    elif ext in ['js', 'jsx', 'ts', 'tsx']:
        return 'javascript'
    elif ext in ['html', 'htm']:
        return 'html'
    elif ext in ['css', 'scss', 'sass']:
        return 'css'
    elif ext in ['json']:
        return 'json'
    elif ext in ['yml', 'yaml']:
        return 'yaml'
    elif ext in ['md']:
        return 'markdown'
    elif ext in ['txt']:
        return 'text'
    elif ext in ['dockerfile']:
        return 'docker'
    elif ext in ['sh', 'bash']:
        return 'shell'
    else:
        return 'other'

@app.route('/api/project/download', methods=['GET'])
def download_project():
    try:
        logger.info("📦 Creating project ZIP for download...")
        zip_buffer = system.create_project_zip()
        
        if zip_buffer:
            # Get current project info
            current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
            if current_project:
                logger.info(f"✅ Created ZIP with {len(current_project.files)} files: {list(current_project.files.keys())}")
            else:
                logger.warning("⚠️ No running project found")
            
            return send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=f'project_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
            )
        else:
            logger.warning("⚠️ No project files to download")
            return jsonify({'success': False, 'error': 'No project files to download'}), 404
    except Exception as e:
        logger.error(f"❌ Error downloading project: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project/files/<path:filename>', methods=['GET'])
def get_file_content(filename):
    try:
        current_project = next((p for p in memory_store.projects.values() if p.status in ["running", "reviewed"]), None)
        if not current_project:
            return jsonify({'success': False, 'error': 'No active project found'}), 404
        
        if filename not in current_project.files:
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        content = current_project.files[filename]
        return jsonify({
            'success': True,
            'filename': filename,
            'content': content,
            'size': len(content.encode('utf-8')),
            'lines': len(content.split('\n')),
            'type': _get_file_type(filename)
        })
    except Exception as e:
        logger.error(f"Error getting file content: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    try:
        uptime = time.time() - memory_store.system_metrics['start_time']
        active_agents = sum(1 for agent in memory_store.agents.values() if agent.is_active)
        
        return jsonify({
            'success': True,
            'metrics': {
                'uptime': int(uptime),
                'active_agents': active_agents,
                'total_agents': len(memory_store.agents),
                'tasks_processed': memory_store.system_metrics['tasks_processed'],
                'messages_sent': memory_store.system_metrics['messages_sent'],
                'files_created': memory_store.system_metrics['files_created'],
                'api_calls': memory_store.system_metrics['api_calls'],
                'errors': memory_store.system_metrics['errors'],
                'task_queue': system.task_queue.get_status()
            }
        })
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/system/reset', methods=['POST'])
def reset_system():
    """Reset all system data - useful for development"""
    try:
        system.stop_project()
        memory_store.clear()
        system.setup_default_agents()
        return jsonify({'success': True, 'message': 'System reset successfully'})
    except Exception as e:
        logger.error(f"Error resetting system: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    logger.info('Client connected')
    emit('connected', {'status': 'success'})

@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')

@socketio.on('request_status')
def handle_status_request():
    system._emit_status_update()

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

if __name__ == '__main__':
    logger.info("🚀 Starting Self-Contained Multi-Agent System...")
    logger.info("📡 Access the application at: http://localhost:5000")
    logger.info("💾 All data stored in memory - no databases required")
    logger.info("🌐 Only external connection: Anthropic API")
    
    try:
        socketio.run(app, debug=False, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
    finally:
        # Cleanup
        executor.shutdown(wait=False)
        asyncio.run(system.anthropic_client.close())
        
        # Clean up temp directories
        for project in memory_store.projects.values():
            if project.temp_dir and os.path.exists(project.temp_dir):
                shutil.rmtree(project.temp_dir, ignore_errors=True)