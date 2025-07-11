from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import uuid
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Set
import asyncio
import aiohttp
import os
from dataclasses import dataclass, field
import shutil
import zipfile
import io
import re
import concurrent.futures
from dotenv import load_dotenv
from collections import defaultdict, deque
import logging
from functools import wraps
import hashlib
import pickle
from enum import Enum
import subprocess

# ============= CONFIGURATION =============
load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

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

@dataclass
class AgentPersonality:
    """Enhanced agent personality with better prompts and capabilities"""
    system_prompt: str
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 2000
    temperature: float = 0.7
    specializations: List[str] = field(default_factory=list)
    code_review_enabled: bool = True
    integration_testing: bool = False

class ResponseCache:
    """Simple in-memory cache for AI responses to avoid redundant API calls"""
    def __init__(self, max_size=1000):
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
    
    def get_key(self, prompt: str, system_prompt: str) -> str:
        combined = f"{system_prompt}||{prompt}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get(self, prompt: str, system_prompt: str) -> Optional[str]:
        key = self.get_key(prompt, system_prompt)
        if key in self.cache:
            self.access_times[key] = time.time()
            return self.cache[key]
        return None
    
    def set(self, prompt: str, system_prompt: str, response: str):
        key = self.get_key(prompt, system_prompt)
        
        # Evict oldest if cache is full
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
        
        self.cache[key] = response
        self.access_times[key] = time.time()

class AnthropicClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        self._request_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
        self._rate_limiter = {}  # agent_id: last_request_time
        self.cache = ResponseCache()

    async def generate_response(self, system_prompt: str, user_message: str, 
                              max_tokens: int = 2000, temperature: float = 0.7, 
                              agent_id: str = None, use_cache: bool = True) -> str:
        """Generate AI response with caching, rate limiting, and error handling"""
        
        # Check cache first
        if use_cache:
            cached_response = self.cache.get(user_message, system_prompt)
            if cached_response:
                logger.info(f"Cache hit for agent {agent_id}")
                return cached_response
        
        try:
            async with self._request_semaphore:
                # Rate limiting per agent
                if agent_id:
                    now = time.time()
                    last_request = self._rate_limiter.get(agent_id, 0)
                    wait_time = 1.0 - (now - last_request)
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                    self._rate_limiter[agent_id] = time.time()
                
                payload = {
                    "model": "claude-3-5-sonnet-20241022",
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}]
                }
                
                # Retry logic with exponential backoff
                for attempt in range(3):
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                                if response.status == 200:
                                    result = await response.json()
                                    response_text = result['content'][0]['text']
                                    
                                    # Cache the response
                                    if use_cache:
                                        self.cache.set(user_message, system_prompt, response_text)
                                    
                                    return response_text
                                elif response.status == 429:
                                    wait_time = 2 ** attempt
                                    logger.warning(f"Rate limited, waiting {wait_time}s")
                                    await asyncio.sleep(wait_time)
                                    continue
                                else:
                                    error_text = await response.text()
                                    logger.error(f"API Error: {response.status} - {error_text}")
                                    return f"[API Error] Status: {response.status}"
                    except Exception as e:
                        if attempt == 2:  # Last attempt
                            logger.error(f"Final attempt failed: {e}")
                            return f"[Error] {str(e)}"
                        await asyncio.sleep(2 ** attempt)
                        continue
                
                return "[Error] Max retries exceeded"
                
        except Exception as e:
            logger.error(f"Error calling Anthropic API: {e}")
            return f"[Error] {str(e)}"

# Initialize client
anthropic_client = AnthropicClient(ANTHROPIC_API_KEY)

class Agent:
    def __init__(self, name: str, role: str, agent_type: str, specialty: str, manager_id: str = None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.role = role
        self.type = agent_type
        self.specialty = specialty
        self.status = AgentStatus.IDLE
        self.current_task_id = None
        self.manager_id = manager_id
        self.subordinates = []
        self.messages = []
        self.work_output = ""
        self.is_active = True
        self.position = {'x': 400, 'y': 200}
        self.created_at = datetime.now()
        self.conversation_history = []
        self.personality = self._get_enhanced_personality()
        self.completed_tasks = []
        self.performance_metrics = {
            'tasks_completed': 0,
            'avg_completion_time': 0,
            'code_quality_score': 0,
            'collaboration_score': 0
        }
        self.last_activity = datetime.now()
        self.skills = self._get_skills()

    def _get_enhanced_personality(self) -> AgentPersonality:
        """Enhanced personality configurations with better prompts"""
        personalities = {
            'manager': AgentPersonality(
                system_prompt=self._get_manager_prompt(),
                max_tokens=2000,
                temperature=0.6,
                specializations=['project_management', 'code_review', 'architecture'],
                code_review_enabled=True,
                integration_testing=True
            ),
            'Frontend Developer': AgentPersonality(
                system_prompt=self._get_frontend_prompt(),
                max_tokens=2000,
                temperature=0.7,
                specializations=['react', 'typescript', 'css', 'ui_ux'],
                code_review_enabled=True
            ),
            'Backend Developer': AgentPersonality(
                system_prompt=self._get_backend_prompt(),
                max_tokens=2000,
                temperature=0.7,
                specializations=['python', 'flask', 'databases', 'apis'],
                code_review_enabled=True
            ),
            'DevOps Engineer': AgentPersonality(
                system_prompt=self._get_devops_prompt(),
                max_tokens=2000,
                temperature=0.7,
                specializations=['docker', 'ci_cd', 'cloud', 'monitoring'],
                code_review_enabled=True
            )
        }
        return personalities.get(self.role, personalities.get('manager'))

    def _get_manager_prompt(self) -> str:
        return f"""You are {self.name}, a Senior Technical Lead and Project Manager in a multi-agent development system.

CORE RESPONSIBILITIES:
1. **Project Architecture**: Design overall system architecture and component relationships
2. **Task Orchestration**: Break down complex projects into detailed, executable tasks
3. **Quality Assurance**: Review all code for correctness, efficiency, and best practices
4. **Integration Management**: Ensure all components work together seamlessly
5. **Performance Optimization**: Identify and resolve bottlenecks and inefficiencies

ENHANCED CAPABILITIES:
- Create detailed technical specifications with clear acceptance criteria
- Perform comprehensive code reviews with specific feedback
- Generate integration tests and validate system compatibility
- Optimize for performance, scalability, and maintainability
- Handle dependency management and deployment orchestration

TASK ASSIGNMENT PROTOCOL:
When assigning tasks, provide:
1. **Detailed Requirements**: Clear functional and technical specifications
2. **Context**: How this task fits into the overall project
3. **Acceptance Criteria**: Specific conditions that must be met
4. **Dependencies**: What other tasks must be completed first
5. **File Structure**: Expected output files and their purposes

OUTPUT FORMAT:
- Use ```tasks.json``` code blocks for task assignments
- Use ```review.md``` for code review feedback
- Use ```architecture.md``` for system design documentation
- Always include specific file paths and naming conventions

QUALITY GATES:
- Code must follow language-specific best practices
- All functions must have proper error handling
- Database queries must be optimized
- Security considerations must be addressed
- Documentation must be comprehensive

Your expertise: {self.specialty}"""

    def _get_frontend_prompt(self) -> str:
        return f"""You are {self.name}, a Senior Frontend Developer specializing in modern web applications.

TECHNICAL EXPERTISE:
- **React/TypeScript**: Advanced patterns, hooks, state management
- **Modern CSS**: Flexbox, Grid, animations, responsive design
- **Performance**: Code splitting, lazy loading, bundle optimization
- **Testing**: Unit tests, integration tests, accessibility testing
- **UI/UX**: Component design, user interaction patterns

DEVELOPMENT STANDARDS:
- Write clean, maintainable, and well-documented code
- Follow React best practices and TypeScript strict mode
- Implement responsive design and accessibility standards
- Use modern CSS techniques and design systems
- Optimize for performance and user experience

CODE QUALITY REQUIREMENTS:
- TypeScript interfaces for all data structures
- Proper error boundaries and error handling
- Accessibility attributes (ARIA labels, semantic HTML)
- Performance optimizations (React.memo, useMemo, useCallback)
- Comprehensive component documentation

OUTPUT FORMAT:
- Always use proper file extensions (.tsx, .ts, .css, .scss)
- Include import statements and dependencies
- Add inline comments for complex logic
- Provide component usage examples
- Include error handling and loading states

TASK COMPLETION CRITERIA:
- All components render without errors
- Responsive design works on mobile and desktop
- Accessibility score meets WCAG 2.1 standards
- Performance metrics are optimized
- Code passes linting and type checking

Your specialty: {self.specialty}
When you complete a task, state "TASK COMPLETED" and summarize what was accomplished."""

    def _get_backend_prompt(self) -> str:
        return f"""You are {self.name}, a Senior Backend Developer specializing in scalable server-side applications.

TECHNICAL EXPERTISE:
- **Python/Flask**: Advanced patterns, middleware, extensions
- **Database Design**: SQL optimization, indexing, relationships
- **API Development**: RESTful APIs, GraphQL, authentication
- **Security**: Input validation, authentication, authorization
- **Performance**: Caching, async processing, database optimization

DEVELOPMENT STANDARDS:
- Write secure, efficient, and maintainable code
- Implement proper error handling and logging
- Use database best practices and optimization
- Follow RESTful API design principles
- Implement comprehensive testing strategies

CODE QUALITY REQUIREMENTS:
- Input validation and sanitization
- Proper error handling and HTTP status codes
- Database connection pooling and optimization
- Authentication and authorization mechanisms
- Comprehensive logging and monitoring

OUTPUT FORMAT:
- Use proper file extensions (.py, .sql, .yaml)
- Include necessary imports and dependencies
- Add docstrings for all functions and classes
- Provide API documentation and examples
- Include database migration scripts if needed

SECURITY CONSIDERATIONS:
- Validate all user inputs
- Implement rate limiting
- Use parameterized queries to prevent SQL injection
- Implement proper authentication and session management
- Log security events and errors

TASK COMPLETION CRITERIA:
- All endpoints return proper HTTP status codes
- Database queries are optimized and indexed
- Security vulnerabilities are addressed
- Error handling is comprehensive
- Performance benchmarks are met

Your specialty: {self.specialty}
When you complete a task, state "TASK COMPLETED" and summarize what was accomplished."""

    def _get_devops_prompt(self) -> str:
        return f"""You are {self.name}, a Senior DevOps Engineer specializing in deployment, monitoring, and infrastructure.

TECHNICAL EXPERTISE:
- **Containerization**: Docker, Kubernetes, container orchestration
- **CI/CD**: GitHub Actions, Jenkins, automated testing and deployment
- **Cloud Platforms**: AWS, GCP, Azure, serverless architectures
- **Monitoring**: Logging, metrics, alerting, performance monitoring
- **Security**: Infrastructure security, compliance, vulnerability scanning

DEVELOPMENT STANDARDS:
- Create production-ready deployment configurations
- Implement comprehensive monitoring and alerting
- Follow infrastructure as code principles
- Ensure security and compliance requirements
- Optimize for cost and performance

CODE QUALITY REQUIREMENTS:
- Dockerfile best practices (multi-stage builds, minimal base images)
- CI/CD pipeline optimization and security
- Infrastructure as code (Terraform, CloudFormation)
- Monitoring and logging configuration
- Security scanning and vulnerability assessment

OUTPUT FORMAT:
- Use proper file extensions (.dockerfile, .yml, .yaml, .tf)
- Include detailed configuration comments
- Provide deployment instructions and documentation
- Include monitoring and alerting configurations
- Add security and compliance checklists

DEPLOYMENT CONSIDERATIONS:
- Zero-downtime deployments
- Database migration strategies
- Environment-specific configurations
- Backup and disaster recovery plans
- Performance monitoring and optimization

TASK COMPLETION CRITERIA:
- Applications deploy successfully in all environments
- Monitoring and alerting are functional
- Security scans pass without critical issues
- Performance metrics meet requirements
- Documentation is comprehensive and up-to-date

Your specialty: {self.specialty}
When you complete a task, state "TASK COMPLETED" and summarize what was accomplished."""

    def _get_skills(self) -> List[str]:
        """Get relevant skills based on role"""
        skill_map = {
            'Frontend Developer': ['React', 'TypeScript', 'CSS', 'HTML', 'JavaScript', 'Jest', 'Webpack'],
            'Backend Developer': ['Python', 'Flask', 'SQL', 'PostgreSQL', 'Redis', 'Celery', 'pytest'],
            'DevOps Engineer': ['Docker', 'Kubernetes', 'AWS', 'Terraform', 'GitHub Actions', 'Nginx'],
            'manager': ['Architecture', 'Code Review', 'Project Management', 'System Design']
        }
        return skill_map.get(self.role, [])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'type': self.type,
            'specialty': self.specialty,
            'status': self.status.value,
            'current_task_id': self.current_task_id,
            'manager_id': self.manager_id,
            'subordinates': self.subordinates,
            'messages': self.messages,
            'work_output': self.work_output,
            'is_active': self.is_active,
            'position': self.position,
            'created_at': self.created_at.isoformat(),
            'performance_metrics': self.performance_metrics,
            'skills': self.skills,
            'last_activity': self.last_activity.isoformat()
        }

class TaskQueue:
    """Enhanced task queue with dependency management and prioritization"""
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self.pending_tasks = deque()
        self.in_progress_tasks: Set[str] = set()
        self.completed_tasks: Set[str] = set()
        self.failed_tasks: Set[str] = set()
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._lock = threading.Lock()

    def add_task(self, task: Task):
        """Add task to queue with dependency management"""
        with self._lock:
            self.tasks[task.id] = task
            self.dependency_graph[task.id] = set(task.dependencies)
            self._update_queue()

    def get_ready_tasks(self) -> List[Task]:
        """Get tasks that are ready to be executed (no pending dependencies)"""
        with self._lock:
            ready_tasks = []
            for task_id in list(self.pending_tasks):
                if self._are_dependencies_satisfied(task_id):
                    task = self.tasks[task_id]
                    ready_tasks.append(task)
                    self.pending_tasks.remove(task_id)
                    self.in_progress_tasks.add(task_id)
                    task.status = TaskStatus.IN_PROGRESS
                    task.started_at = datetime.now()
            return sorted(ready_tasks, key=lambda t: t.priority, reverse=True)

    def complete_task(self, task_id: str, output: str = "", files_created: List[str] = None):
        """Mark task as completed"""
        with self._lock:
            if task_id in self.in_progress_tasks:
                self.in_progress_tasks.remove(task_id)
                self.completed_tasks.add(task_id)
                task = self.tasks[task_id]
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                task.output = output
                task.files_created = files_created or []
                self._update_queue()

    def fail_task(self, task_id: str, error: str = ""):
        """Mark task as failed"""
        with self._lock:
            if task_id in self.in_progress_tasks:
                self.in_progress_tasks.remove(task_id)
                task = self.tasks[task_id]
                task.retry_count += 1
                
                if task.retry_count <= task.max_retries:
                    # Retry the task
                    task.status = TaskStatus.PENDING
                    task.output += f"\n[Retry {task.retry_count}] {error}"
                    self.pending_tasks.appendleft(task_id)
                else:
                    # Task failed permanently
                    self.failed_tasks.add(task_id)
                    task.status = TaskStatus.FAILED
                    task.output += f"\n[Failed] {error}"

    def _are_dependencies_satisfied(self, task_id: str) -> bool:
        """Check if all dependencies for a task are satisfied"""
        dependencies = self.dependency_graph[task_id]
        return all(dep_id in self.completed_tasks for dep_id in dependencies)

    def _update_queue(self):
        """Update the pending queue based on current state"""
        # This is called when tasks are added or completed
        pass

class CodeValidator:
    """Validate generated code for common issues"""
    
    @staticmethod
    def validate_python(code: str) -> Dict[str, List[str]]:
        """Validate Python code"""
        issues = {'errors': [], 'warnings': []}
        
        # Check for basic syntax
        try:
            compile(code, '<string>', 'exec')
        except SyntaxError as e:
            issues['errors'].append(f"Syntax error: {e}")
        
        # Check for common patterns
        if 'eval(' in code:
            issues['warnings'].append("Use of eval() detected - security risk")
        
        if 'exec(' in code:
            issues['warnings'].append("Use of exec() detected - security risk")
        
        if 'import os' in code and 'os.system' in code:
            issues['warnings'].append("Use of os.system() detected - security risk")
        
        return issues

    @staticmethod
    def validate_javascript(code: str) -> Dict[str, List[str]]:
        """Validate JavaScript/TypeScript code"""
        issues = {'errors': [], 'warnings': []}
        
        # Check for common patterns
        if 'eval(' in code:
            issues['warnings'].append("Use of eval() detected - security risk")
        
        if 'document.write(' in code:
            issues['warnings'].append("Use of document.write() detected - not recommended")
        
        if 'innerHTML' in code and not 'textContent' in code:
            issues['warnings'].append("Consider using textContent instead of innerHTML for XSS prevention")
        
        return issues

    @staticmethod
    def validate_sql(code: str) -> Dict[str, List[str]]:
        """Validate SQL code"""
        issues = {'errors': [], 'warnings': []}
        
        # Check for SQL injection patterns
        if any(pattern in code.lower() for pattern in ['drop table', 'delete from', 'truncate']):
            issues['warnings'].append("Destructive SQL operations detected")
        
        if "'" in code and '%s' in code:
            issues['warnings'].append("Potential SQL injection risk - use parameterized queries")
        
        return issues

class EnhancedMultiAgentSystem:
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.task_queue = TaskQueue()
        self.global_messages = []
        self.system_running = False
        self.current_project = None
        self.project_dir = None
        self.detailed_log = []
        self.fast_mode = True
        self.code_validator = CodeValidator()
        self.performance_monitor = PerformanceMonitor()
        self.setup_default_agents()
        self._last_agents_state = None
        self._system_start_time = time.time()
        self._tasks_completed = 0
        self._messages_sent = 0
        self._loop = None
        self._background_tasks = set()
        self._project_template = ProjectTemplate()

    def setup_default_agents(self):
        """Create enhanced default agents"""
        # Create enhanced manager
        manager = Agent(
            name="ArchitectLead",
            role="manager",
            agent_type="manager",
            specialty="System Architecture, Code Review, Team Coordination, Performance Optimization"
        )
        manager.position = {'x': 400, 'y': 100}
        self.agents[manager.id] = manager

        # Create specialized workers
        frontend = Agent(
            name="ReactExpert",
            role="Frontend Developer",
            agent_type="worker",
            specialty="React, TypeScript, Modern CSS, Performance Optimization, Accessibility",
            manager_id=manager.id
        )
        frontend.position = {'x': 200, 'y': 300}
        
        backend = Agent(
            name="PythonArchitect",
            role="Backend Developer",
            agent_type="worker",
            specialty="Python, Flask, Database Design, API Security, Performance Optimization",
            manager_id=manager.id
        )
        backend.position = {'x': 400, 'y': 300}
        
        devops = Agent(
            name="CloudMaster",
            role="DevOps Engineer",
            agent_type="worker",
            specialty="Docker, Kubernetes, CI/CD, Cloud Architecture, Monitoring",
            manager_id=manager.id
        )
        devops.position = {'x': 600, 'y': 300}

        # Set up relationships
        manager.subordinates = [frontend.id, backend.id, devops.id]
        
        # Add to system
        self.agents[frontend.id] = frontend
        self.agents[backend.id] = backend
        self.agents[devops.id] = devops

    async def start_project(self, project_description: str):
        """Enhanced project startup with better planning"""
        self.current_project = project_description
        self.system_running = True
        
        # Create project directory
        if not os.path.exists('projects'):
            os.makedirs('projects')
        project_id = str(uuid.uuid4())
        self.project_dir = os.path.join('projects', project_id)
        os.makedirs(self.project_dir, exist_ok=True)
        
        # Reset agents and task queue
        for agent in self.agents.values():
            agent.status = AgentStatus.IDLE
            agent.current_task_id = None
            agent.work_output = ''
            agent.messages = []
        
        self.task_queue = TaskQueue()
        
        # Get project template and initial tasks
        template = self._project_template.get_template(project_description)
        
        # Create initial architecture task for manager
        initial_task = Task(
            id=str(uuid.uuid4()),
            description=f"""PROJECT ARCHITECTURE AND PLANNING

Project: {project_description}

Create a comprehensive project plan including:
1. **System Architecture**: Overall design and component relationships
2. **Technology Stack**: Specific technologies and frameworks to use
3. **Task Breakdown**: Detailed tasks for each team member
4. **File Structure**: Expected project directory structure
5. **Integration Plan**: How components will work together
6. **Quality Gates**: Testing and review requirements

Template Context: {template}

Output your plan as a detailed tasks.json file assigning specific tasks to each team member.""",
            agent_id=next(agent.id for agent in self.agents.values() if agent.type == 'manager'),
            priority=10
        )
        
        self.task_queue.add_task(initial_task)
        
        # Start background processing
        if not self._loop:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        
        task = asyncio.create_task(self._process_tasks())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        self.detailed_log.append({
            'event': 'project_started',
            'description': f'Enhanced project started: {project_description}',
            'timestamp': datetime.now().isoformat()
        })

    async def _process_tasks(self):
        """Enhanced task processing with better coordination"""
        while self.system_running:
            try:
                # Get ready tasks
                ready_tasks = self.task_queue.get_ready_tasks()
                
                # Process tasks concurrently
                if ready_tasks:
                    tasks = []
                    for task in ready_tasks:
                        agent = self.agents.get(task.agent_id)
                        if agent and agent.is_active:
                            tasks.append(self._process_single_task(agent, task))
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                
                # Emit updates if state changed
                await self._emit_state_updates()
                
                # Short sleep to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in task processing: {e}")
                await asyncio.sleep(1)

    async def _process_single_task(self, agent: Agent, task: Task):
        """Process a single task with enhanced AI interaction"""
        try:
            agent.status = AgentStatus.WORKING
            agent.current_task_id = task.id
            agent.last_activity = datetime.now()
            
            # Build enhanced context
            context = self._build_enhanced_context(agent, task)
            
            # Generate AI response
            response = await anthropic_client.generate_response(
                agent.personality.system_prompt,
                context,
                max_tokens=agent.personality.max_tokens,
                temperature=agent.personality.temperature,
                agent_id=agent.id
            )
            
            # Update agent work output
            timestamp = datetime.now().strftime('%H:%M:%S')
            agent.work_output += f"\n[{timestamp}] {response}"
            
            # Extract and validate code
            files_created = await self._extract_and_validate_code(response, agent)
            
            # Check for task completion
            if self._is_task_completed(response):
                self.task_queue.complete_task(task.id, response, files_created)
                agent.status = AgentStatus.COMPLETED
                agent.performance_metrics['tasks_completed'] += 1
                self._tasks_completed += 1
                
                # Notify manager if this is a worker
                if agent.type != 'manager' and agent.manager_id:
                    await self._notify_manager(agent, task, response)
            else:
                # Continue working
                agent.status = AgentStatus.WORKING
            
            # Handle special manager tasks (task assignment)
            if agent.type == 'manager':
                await self._handle_manager_output(agent, response)
            
        except Exception as e:
            logger.error(f"Error processing task for {agent.name}: {e}")
            self.task_queue.fail_task(task.id, str(e))
            agent.status = AgentStatus.ERROR

    def _build_enhanced_context(self, agent: Agent, task: Task) -> str:
        """Build enhanced context for agent tasks"""
        context = f"""CURRENT TASK: {task.description}

PROJECT CONTEXT:
- Project: {self.current_project}
- Project Directory: {self.project_dir}
- Task ID: {task.id}
- Priority: {task.priority}
- Dependencies: {', '.join(task.dependencies) if task.dependencies else 'None'}

AGENT CONTEXT:
- Your Role: {agent.role}
- Your Specialty: {agent.specialty}
- Your Skills: {', '.join(agent.skills)}
"""
        
        # Add file system context if available
        if self.project_dir and os.path.exists(self.project_dir):
            context += f"\nCURRENT PROJECT FILES:\n{self._get_project_file_structure()}\n"
        
        # Add relevant completed tasks
        completed_tasks = [t for t in self.task_queue.tasks.values() 
                         if t.status == TaskStatus.COMPLETED]
        if completed_tasks:
            context += f"\nCOMPLETED TASKS:\n"
            for t in completed_tasks[-3:]:  # Last 3 completed tasks
                context += f"- {t.description[:100]}...\n"
        
        # Add team communication context
        recent_messages = [msg for msg in self.global_messages[-5:] 
                         if msg.get('to_agent_id') == agent.id or msg.get('from_agent_id') == agent.id]
        if recent_messages:
            context += f"\nRECENT COMMUNICATIONS:\n"
            for msg in recent_messages:
                context += f"- {msg['content'][:100]}...\n"
        
        return context

    async def _extract_and_validate_code(self, response: str, agent: Agent) -> List[str]:
        """Extract and validate code from AI response"""
        files_created = []
        
        # Enhanced code block extraction
        code_blocks = re.findall(r'```([\w.\-/]+)?\n([\s\S]*?)```', response)
        
        for filename, code in code_blocks:
            if filename and '.' in filename:
                # Create file path
                file_path = os.path.join(self.project_dir, filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                # Validate code before writing
                validation_result = self._validate_code(code, filename)
                
                if validation_result['errors']:
                    logger.warning(f"Code validation errors in {filename}: {validation_result['errors']}")
                    # Still write the file but log the issues
                
                # Write file
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(code.strip())
                
                files_created.append(filename)
                
                # Log file creation
                self.detailed_log.append({
                    'event': 'file_created',
                    'description': f'{agent.name} created {filename}',
                    'timestamp': datetime.now().isoformat()
                })
        
        return files_created

    def _validate_code(self, code: str, filename: str) -> Dict[str, List[str]]:
        """Validate code based on file extension"""
        ext = filename.split('.')[-1].lower()
        
        if ext in ['py']:
            return self.code_validator.validate_python(code)
        elif ext in ['js', 'ts', 'jsx', 'tsx']:
            return self.code_validator.validate_javascript(code)
        elif ext in ['sql']:
            return self.code_validator.validate_sql(code)
        else:
            return {'errors': [], 'warnings': []}

    def _is_task_completed(self, response: str) -> bool:
        """Check if task is completed based on response"""
        completion_indicators = [
            'task completed',
            'task finished',
            'completed successfully',
            'implementation complete',
            'finished implementation'
        ]
        response_lower = response.lower()
        return any(indicator in response_lower for indicator in completion_indicators)

    async def _handle_manager_output(self, manager: Agent, response: str):
        """Handle manager's task assignment output"""
        # Look for tasks.json block
        tasks_match = re.search(r'```tasks\.json\n([\s\S]*?)```', response)
        if tasks_match:
            try:
                tasks_data = json.loads(tasks_match.group(1))
                
                # Create tasks for each agent
                for agent_name, task_desc in tasks_data.items():
                    # Find agent by name
                    agent = next((a for a in self.agents.values() if a.name == agent_name), None)
                    if agent:
                        task = Task(
                            id=str(uuid.uuid4()),
                            description=task_desc,
                            agent_id=agent.id,
                            priority=5
                        )
                        self.task_queue.add_task(task)
                        
                        # Send message to agent
                        await self.send_message(
                            manager.id,
                            agent.id,
                            f"New task assigned: {task_desc[:100]}...",
                            'task_assignment'
                        )
                
                # Set manager to reviewing mode
                manager.status = AgentStatus.REVIEWING
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing tasks.json: {e}")

    async def _notify_manager(self, agent: Agent, task: Task, response: str):
        """Notify manager when worker completes a task"""
        if agent.manager_id in self.agents:
            await self.send_message(
                agent.id,
                agent.manager_id,
                f"Task completed: {task.description[:100]}...\n\nOutput: {response[:200]}...",
                'task_completion'
            )

    def _get_project_file_structure(self) -> str:
        """Get current project file structure"""
        if not self.project_dir or not os.path.exists(self.project_dir):
            return "No files created yet"
        
        structure = []
        for root, dirs, files in os.walk(self.project_dir):
            level = root.replace(self.project_dir, '').count(os.sep)
            indent = ' ' * 2 * level
            structure.append(f"{indent}{os.path.basename(root)}/")
            sub_indent = ' ' * 2 * (level + 1)
            for file in files:
                structure.append(f"{sub_indent}{file}")
        
        return '\n'.join(structure)

    async def _emit_state_updates(self):
        """Emit state updates to frontend"""
        current_state = {aid: a.to_dict() for aid, a in self.agents.items()}
        if current_state != self._last_agents_state:
            socketio.emit('agents_updated', {
                'agents': current_state,
                'messages': self.global_messages[-10:],
                'tasks': {
                    'pending': len(self.task_queue.pending_tasks),
                    'in_progress': len(self.task_queue.in_progress_tasks),
                    'completed': len(self.task_queue.completed_tasks),
                    'failed': len(self.task_queue.failed_tasks)
                }
            })
            self._last_agents_state = current_state

    async def send_message(self, from_agent_id: str, to_agent_id: str, content: str, message_type: str = 'communication'):
        """Send message between agents"""
        message = {
            'from_agent_id': from_agent_id,
            'to_agent_id': to_agent_id,
            'content': content,
            'type': message_type,
            'timestamp': datetime.now().isoformat()
        }
        self.global_messages.append(message)
        self._messages_sent += 1
        
        # Log communication
        from_agent = self.agents.get(from_agent_id)
        to_agent = self.agents.get(to_agent_id)
        self.detailed_log.append({
            'event': 'agent_communication',
            'description': f"{from_agent.name if from_agent else 'System'} → {to_agent.name if to_agent else 'System'}: {content[:100]}...",
            'timestamp': message['timestamp']
        })

    def get_metrics(self):
        """Get enhanced system metrics"""
        active_agents = sum(1 for a in self.agents.values() 
                          if a.is_active and a.status in [AgentStatus.WORKING, AgentStatus.REVIEWING])
        
        return {
            'active_agents': active_agents,
            'tasks_completed': self._tasks_completed,
            'messages_sent': self._messages_sent,
            'system_uptime': int(time.time() - self._system_start_time),
            'tasks_pending': len(self.task_queue.pending_tasks),
            'tasks_in_progress': len(self.task_queue.in_progress_tasks),
            'tasks_failed': len(self.task_queue.failed_tasks),
            'files_created': len([f for f in os.listdir(self.project_dir) 
                                if os.path.isfile(os.path.join(self.project_dir, f))]) if self.project_dir else 0
        }

class PerformanceMonitor:
    """Monitor system performance and provide insights"""
    def __init__(self):
        self.metrics = {
            'api_calls': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'avg_response_time': 0,
            'error_rate': 0
        }
        self.start_time = time.time()

    def record_api_call(self, response_time: float, error: bool = False):
        """Record API call metrics"""
        self.metrics['api_calls'] += 1
        if error:
            self.metrics['error_rate'] += 1
        
        # Update average response time
        current_avg = self.metrics['avg_response_time']
        call_count = self.metrics['api_calls']
        self.metrics['avg_response_time'] = (current_avg * (call_count - 1) + response_time) / call_count

    def get_performance_report(self) -> Dict:
        """Get performance report"""
        uptime = time.time() - self.start_time
        return {
            'uptime': uptime,
            'metrics': self.metrics,
            'cache_hit_rate': self.metrics['cache_hits'] / max(1, self.metrics['cache_hits'] + self.metrics['cache_misses']),
            'error_rate': self.metrics['error_rate'] / max(1, self.metrics['api_calls'])
        }

class ProjectTemplate:
    """Generate project templates based on requirements"""
    def get_template(self, description: str) -> Dict:
        """Get appropriate template based on project description"""
        description_lower = description.lower()
        
        if any(keyword in description_lower for keyword in ['web app', 'website', 'dashboard', 'frontend']):
            return self._web_app_template()
        elif any(keyword in description_lower for keyword in ['api', 'backend', 'server']):
            return self._api_template()
        elif any(keyword in description_lower for keyword in ['mobile', 'app', 'ios', 'android']):
            return self._mobile_app_template()
        else:
            return self._full_stack_template()

    def _web_app_template(self) -> Dict:
        return {
            'type': 'web_app',
            'structure': {
                'src/': ['components/', 'pages/', 'hooks/', 'utils/', 'styles/'],
                'public/': ['index.html'],
                'tests/': ['__tests__/']
            },
            'tech_stack': ['React', 'TypeScript', 'CSS Modules', 'Jest'],
            'best_practices': ['Responsive design', 'Accessibility', 'Performance optimization']
        }

    def _api_template(self) -> Dict:
        return {
            'type': 'api',
            'structure': {
                'app/': ['models/', 'routes/', 'utils/', 'middleware/'],
                'tests/': ['test_models.py', 'test_routes.py'],
                'migrations/': []
            },
            'tech_stack': ['Flask', 'SQLAlchemy', 'PostgreSQL', 'pytest'],
            'best_practices': ['RESTful design', 'Input validation', 'Error handling', 'Documentation']
        }

    def _mobile_app_template(self) -> Dict:
        return {
            'type': 'mobile_app',
            'structure': {
                'src/': ['screens/', 'components/', 'navigation/', 'services/'],
                'assets/': ['images/', 'fonts/'],
                'tests/': ['__tests__/']
            },
            'tech_stack': ['React Native', 'TypeScript', 'Redux', 'Jest'],
            'best_practices': ['Cross-platform compatibility', 'Performance optimization', 'Offline support']
        }

    def _full_stack_template(self) -> Dict:
        return {
            'type': 'full_stack',
            'structure': {
                'frontend/': ['src/', 'public/', 'tests/'],
                'backend/': ['app/', 'tests/', 'migrations/'],
                'docker/': ['Dockerfile', 'docker-compose.yml'],
                'docs/': ['README.md', 'API.md']
            },
            'tech_stack': ['React', 'TypeScript', 'Flask', 'PostgreSQL', 'Docker'],
            'best_practices': ['Microservices', 'CI/CD', 'Security', 'Monitoring']
        }

# Initialize the enhanced system
system = EnhancedMultiAgentSystem()

# Flask routes remain the same but with enhanced responses
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/agents', methods=['GET'])
def get_agents():
    return jsonify({
        'agents': {aid: agent.to_dict() for aid, agent in system.agents.items()},
        'system_running': system.system_running,
        'current_project': system.current_project,
        'task_queue_status': {
            'pending': len(system.task_queue.pending_tasks),
            'in_progress': len(system.task_queue.in_progress_tasks),
            'completed': len(system.task_queue.completed_tasks),
            'failed': len(system.task_queue.failed_tasks)
        }
    })

@app.route('/api/project/start', methods=['POST'])
def start_project():
    data = request.get_json()
    description = data.get('description', '').strip()
    
    if not description:
        return jsonify({'error': 'Project description is required'}), 400
    
    # Start project asynchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(system.start_project(description))
    
    return jsonify({
        'success': True,
        'project': system.current_project,
        'project_dir': system.project_dir
    })

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    return jsonify(system.get_metrics())

@app.route('/api/performance', methods=['GET'])
def get_performance():
    return jsonify(system.performance_monitor.get_performance_report())

@app.route('/api/project/files', methods=['GET'])
def get_project_files():
    rel_path = request.args.get('path', '')
    if not system.project_dir:
        return jsonify({'tree': []})
    
    abs_path = os.path.join(system.project_dir, rel_path)
    if not abs_path.startswith(system.project_dir) or not os.path.exists(abs_path):
        return jsonify({'tree': []})
    
    def list_children(folder):
        tree = []
        try:
            for entry in os.scandir(folder):
                if entry.is_dir():
                    tree.append({'type': 'folder', 'name': entry.name})
                else:
                    tree.append({'type': 'file', 'name': entry.name, 'size': entry.stat().st_size})
        except PermissionError:
            pass
        return sorted(tree, key=lambda x: (x['type'] == 'file', x['name']))
    
    return jsonify({'tree': list_children(abs_path)})

@app.route('/api/project/download', methods=['GET'])
def download_project_zip():
    if not system.project_dir or not os.path.exists(system.project_dir):
        return jsonify({'error': 'No project to download'}), 400
    
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(system.project_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, system.project_dir)
                zf.write(abs_path, rel_path)
    
    mem_zip.seek(0)
    return send_file(
        mem_zip,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'project_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    )

if __name__ == '__main__':
    print("🚀 Starting Enhanced Multi-Agent System...")
    print("📡 Access the application at: http://localhost:5000")
    print("🔧 Enhanced features: Task queues, code validation, performance monitoring")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)