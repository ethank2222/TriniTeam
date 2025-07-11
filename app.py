from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import uuid
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
import asyncio
import aiohttp
import os
from dataclasses import dataclass
import shutil
import zipfile
import io
import re
import concurrent.futures
from dotenv import load_dotenv

# ============= CONFIGURATION =============
# Load environment variables from .env file
load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
# =========================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

@dataclass
class AgentPersonality:
    """Defines the personality and behavior of each agent type"""
    system_prompt: str
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 1000
    temperature: float = 0.7

class AnthropicClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        self._last_request_time = {}  # agent_id: timestamp

    async def generate_response(self, system_prompt: str, user_message: str, max_tokens: int = 1000, temperature: float = 0.7, agent_id: str = None) -> str:
        """Generate a response using the Anthropic API with politeness checks and retries"""
        try:
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            }
            # Politeness: per-agent rate limit (1 req/sec)
            if agent_id:
                now = time.time()
                last = self._last_request_time.get(agent_id, 0)
                wait = 1.0 - (now - last)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request_time[agent_id] = time.time()
            # Retry logic
            retries = 3
            delay = 1.5
            for attempt in range(retries):
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.base_url, headers=self.headers, json=payload) as response:
                        if response.status == 200:
                            result = await response.json()
                            return result['content'][0]['text']
                        elif response.status == 529 or (response.status == 400 and 'overloaded' in await response.text()):
                            if attempt < retries - 1:
                                await asyncio.sleep(delay)
                                delay *= 2
                                continue
                            else:
                                return "[Polite Notice] The system is currently overloaded. Please wait a moment and try again."
                        else:
                            error_text = await response.text()
                            print(f"API Error: {response.status} - {error_text}")
                            return f"[API Error] Status: {response.status}"
        except Exception as e:
            print(f"Error calling Anthropic API: {e}")
            return f"[Error] {str(e)}"

# Initialize Anthropic client
anthropic_client = AnthropicClient(ANTHROPIC_API_KEY)

class Agent:
    def __init__(self, name: str, role: str, agent_type: str, specialty: str, manager_id: str = None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.role = role
        self.type = agent_type  # 'manager' or 'worker'
        self.specialty = specialty
        self.status = 'idle'  # idle, working, completed, error
        self.current_task = None
        self.manager_id = manager_id
        self.subordinates = []
        self.messages = []
        self.work_output = ""
        self.is_active = True
        self.position = {'x': 400, 'y': 200}
        self.created_at = datetime.now()
        self.conversation_history = []
        self.personality = self._get_personality()

    def _get_personality(self) -> AgentPersonality:
        personalities = {
            'manager': AgentPersonality(
                system_prompt=(
                    f"You are {{self.name}}, a {{self.role}} in a multi-agent development system.\n\n"
                    f"Your role: {{self.role}}\nYour specialty: {{self.specialty}}\nYour type: Project Manager/Team Lead\n\n"
                    f"Your responsibilities:\n"
                    f"- Break down the project into the largest possible, self-contained, specification-driven tasks for each agent.\n"
                    f"- Assign tasks that allow agents to work autonomously for as long as possible, minimizing the need for back-and-forth communication.\n"
                    f"- Only communicate when a major milestone is reached, or when a handoff or integration is required.\n"
                    f"- Use structured formats (JSON, YAML, bullet points) for all communications.\n"
                    f"- Focus on requirements, interfaces, and deliverables.\n"
                    f"- Each message should be actionable and unambiguous.\n\n"
                    f"When given a project, create a comprehensive plan and assign large, independent tasks to each agent. Avoid micro-managing or sending small tasks. If you assign a task that involves modifying files, ensure the agent receives the current contents of those files.\n"
                    f"Always output code in the format ```filename.ext\ncode...``` for every file you create or modify.\n"
                    f"After all agents report completion, review the actual files in the project directory. If any required files are missing or incomplete, assign correction tasks to the appropriate agent."
                )
            ),
            'Frontend Developer': AgentPersonality(
                system_prompt=(
                    f"You are {{self.name}}, a strictly technical {{self.role}} in a multi-agent development system.\n\n"
                    f"Your role: {{self.role}}\nYour specialty: {{self.specialty}}\nYour type: Frontend Developer\n\n"
                    f"Your responsibilities:\n"
                    f"- When assigned a task, plan, implement, and test as much as possible in one cycle.\n"
                    f"- Make all necessary changes across multiple files if needed.\n"
                    f"- Only communicate when a major milestone is reached, or when you are blocked.\n"
                    f"- Use structured formats (JSON, YAML, bullet points) for all communications.\n"
                    f"- Focus on requirements, interfaces, and deliverables.\n"
                    f"- Each message should be actionable and unambiguous.\n\n"
                    f"When given a task, work autonomously and deliver a complete, specification-driven solution. Output all updated files in code blocks labeled with the filename.\n"
                    f"Always output code in the format ```filename.ext\ncode...``` for every file you create or modify.\n"
                    f"If you do not output any code, explain why."
                )
            ),
            'Backend Developer': AgentPersonality(
                system_prompt=(
                    f"You are {{self.name}}, a strictly technical {{self.role}} in a multi-agent development system.\n\n"
                    f"Your role: {{self.role}}\nYour specialty: {{self.specialty}}\nYour type: Backend Developer\n\n"
                    f"Your responsibilities:\n"
                    f"- When assigned a task, plan, implement, and test as much as possible in one cycle.\n"
                    f"- Make all necessary changes across multiple files if needed.\n"
                    f"- Only communicate when a major milestone is reached, or when you are blocked.\n"
                    f"- Use structured formats (JSON, YAML, bullet points) for all communications.\n"
                    f"- Focus on requirements, interfaces, and deliverables.\n"
                    f"- Each message should be actionable and unambiguous.\n\n"
                    f"When given a task, work autonomously and deliver a complete, specification-driven solution. Output all updated files in code blocks labeled with the filename.\n"
                    f"Always output code in the format ```filename.ext\ncode...``` for every file you create or modify.\n"
                    f"If you do not output any code, explain why."
                )
            ),
            'DevOps Engineer': AgentPersonality(
                system_prompt=(
                    f"You are {{self.name}}, a strictly technical {{self.role}} in a multi-agent development system.\n\n"
                    f"Your role: {{self.role}}\nYour specialty: {{self.specialty}}\nYour type: DevOps Engineer\n\n"
                    f"Your responsibilities:\n"
                    f"- When assigned a task, plan, implement, and test as much as possible in one cycle.\n"
                    f"- Make all necessary changes across multiple files if needed.\n"
                    f"- Only communicate when a major milestone is reached, or when you are blocked.\n"
                    f"- Use structured formats (JSON, YAML, bullet points) for all communications.\n"
                    f"- Focus on requirements, interfaces, and deliverables.\n"
                    f"- Each message should be actionable and unambiguous.\n\n"
                    f"When given a task, work autonomously and deliver a complete, specification-driven solution. Output all updated files in code blocks labeled with the filename.\n"
                    f"Always output code in the format ```filename.ext\ncode...``` for every file you create or modify.\n"
                    f"If you do not output any code, explain why."
                )
            )
        }
        return personalities.get(self.role, personalities.get('manager'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'type': self.type,
            'specialty': self.specialty,
            'status': self.status,
            'current_task': self.current_task,
            'manager_id': self.manager_id,
            'subordinates': self.subordinates,
            'messages': self.messages,
            'work_output': self.work_output,
            'is_active': self.is_active,
            'position': self.position,
            'created_at': self.created_at.isoformat()
        }

# --- Update MultiAgentSystem for robust metrics ---
class MultiAgentSystem:
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.global_messages = []
        self.system_running = False
        self.current_project = None
        self.project_dir = None
        self.detailed_log = []
        self.task_queue = []
        self.fast_mode = True
        self.setup_default_agents()
        self._last_agents_state = None
        self._system_start_time = time.time()
        self._tasks_completed = 0
        self._messages_sent = 0

    def increment_tasks_completed(self, agent=None):
        self._tasks_completed += 1
        if agent:
            if not hasattr(agent, 'tasks_completed'):
                agent.tasks_completed = 0
            agent.tasks_completed += 1

    def increment_messages_sent(self):
        self._messages_sent += 1

    def get_metrics(self):
        # Only count agents that are active and not completed or error
        active_agents = sum(1 for a in self.agents.values() if a.is_active and a.status in ('working', 'idle'))
        return {
            'active_agents': active_agents,
            'tasks_completed': self._tasks_completed,
            'messages_sent': self._messages_sent,
            'system_uptime': int(time.time() - self._system_start_time)
        }

    def setup_default_agents(self):
        # Create default manager
        manager = Agent(
            name="CodeLead",
            role="manager",
            agent_type="manager",
            specialty="Task delegation, integration oversight, quality control"
        )
        manager.position = {'x': 400, 'y': 100}
        self.agents[manager.id] = manager

        # Create default workers
        frontend = Agent(
            name="UIAgent",
            role="Frontend Developer",
            agent_type="worker",
            specialty="React, TypeScript, UI/UX, State Management",
            manager_id=manager.id
        )
        frontend.position = {'x': 200, 'y': 300}
        
        backend = Agent(
            name="APIAgent",
            role="Backend Developer",
            agent_type="worker",
            specialty="Python, Flask, Database, API Design",
            manager_id=manager.id
        )
        backend.position = {'x': 400, 'y': 300}
        
        devops = Agent(
            name="DeployAgent",
            role="DevOps Engineer",
            agent_type="worker",
            specialty="Docker, CI/CD, Cloud Infrastructure, Monitoring",
            manager_id=manager.id
        )
        devops.position = {'x': 600, 'y': 300}

        # Set up relationships
        manager.subordinates = [frontend.id, backend.id, devops.id]
        
        # Add to system
        self.agents[frontend.id] = frontend
        self.agents[backend.id] = backend
        self.agents[devops.id] = devops

    def add_agent(self, name: str, role: str, agent_type: str, specialty: str, manager_id: str = None) -> str:
        agent = Agent(name, role, agent_type, specialty, manager_id)
        self.agents[agent.id] = agent
        
        # If this agent has a manager, add to manager's subordinates
        if manager_id and manager_id in self.agents:
            self.agents[manager_id].subordinates.append(agent.id)
        
        return agent.id

    def remove_agent(self, agent_id: str) -> bool:
        if agent_id not in self.agents:
            return False
        
        agent = self.agents[agent_id]
        
        # Remove from manager's subordinates
        if agent.manager_id and agent.manager_id in self.agents:
            manager = self.agents[agent.manager_id]
            if agent_id in manager.subordinates:
                manager.subordinates.remove(agent_id)
        
        # Reassign subordinates if this is a manager
        if agent.type == 'manager' and agent.subordinates:
            for sub_id in agent.subordinates:
                if sub_id in self.agents:
                    self.agents[sub_id].manager_id = None
        
        del self.agents[agent_id]
        return True

    def start_project(self, project_description: str):
        import uuid, os
        self.current_project = project_description
        self.system_running = True
        # Create a unique project directory
        if not os.path.exists('projects'):
            os.makedirs('projects')
        project_id = str(uuid.uuid4())
        self.project_dir = os.path.join('projects', project_id)
        os.makedirs(self.project_dir, exist_ok=True)
        # Reset all agents
        for agent in self.agents.values():
            agent.status = 'idle'
            agent.current_task = None
            agent.work_output = ''
            agent.messages = []
        # Set manager and workers to working state and assign initial tasks
        for agent in self.agents.values():
            if agent.type == 'manager':
                agent.current_task = project_description
                agent.status = 'working'
            else:
                agent.current_task = ''
                agent.status = 'working'
        self.detailed_log.append({'event': 'project_started', 'description': f'Project started: {project_description}', 'timestamp': datetime.now().isoformat()})

    def send_message(self, from_agent_id: str, to_agent_id: str, content: str, message_type: str = 'communication'):
        message = {
            'from_agent_id': from_agent_id,
            'to_agent_id': to_agent_id,
            'content': content,
            'type': message_type,
            'timestamp': datetime.now().isoformat()
        }
        self.global_messages.append(message)
        self.increment_messages_sent() # Increment messages sent
        # Log the communication in detail
        from_agent = self.agents.get(from_agent_id)
        to_agent = self.agents.get(to_agent_id)
        self.detailed_log.append({
            'event': 'agent_communication',
            'description': f"{from_agent.name if from_agent else from_agent_id} sent a '{message_type}' message to {to_agent.name if to_agent else to_agent_id}: {content}",
            'timestamp': message['timestamp']
        })
        return message

    def simulate_agent_work(self):
        """Process agent work in parallel using a thread pool for maximum speed."""
        import threading
        import time
        processed = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            while self.system_running:
                try:
                    futures = []
                    for agent in self.agents.values():
                        if agent.is_active and agent.status == 'working' and agent.id not in processed:
                            processed.add(agent.id)
                            futures.append(executor.submit(self._run_agent_sync, agent, processed))
                    # If all subordinates are completed, trigger manager review immediately
                    for agent in self.agents.values():
                        if agent.type == 'manager' and agent.subordinates:
                            sub_statuses = [self.agents[sub_id].status for sub_id in agent.subordinates if sub_id in self.agents]
                            if all(s == 'completed' for s in sub_statuses) and agent.status != 'working':
                                agent.status = 'working'
                                if agent.id not in processed:
                                    processed.add(agent.id)
                                    futures.append(executor.submit(self._run_agent_sync, agent, processed))
                    # Wait for any completed
                    for future in concurrent.futures.as_completed(futures):
                        pass
                    # Only emit UI updates if state changed
                    agents_state = {aid: a.to_dict() for aid, a in self.agents.items()}
                    if agents_state != self._last_agents_state:
                        socketio.emit('agents_updated', {
                            'agents': agents_state,
                            'messages': self.global_messages[-10:]
                        })
                        self._last_agents_state = agents_state
                    time.sleep(0.05)
                except Exception as e:
                    print(f"Error in simulate_agent_work: {e}")
                    time.sleep(0.2)

    def _run_agent_sync(self, agent, processed):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.process_agent_work(agent))
        processed.discard(agent.id)

    async def process_agent_work(self, agent: Agent):
        """Process work for a single agent using AI"""
        try:
            # Create context for the agent
            context = self.build_agent_context(agent)

            # --- Worker logic: if completed, do not process further ---
            if agent.type != 'manager' and agent.status == 'completed':
                return

            # --- Manager logic: only process if at least one subordinate is working or all are completed ---
            if agent.type == 'manager' and agent.subordinates:
                sub_statuses = [self.agents[sub_id].status for sub_id in agent.subordinates if sub_id in self.agents]
                if not any(s == 'working' for s in sub_statuses) and not all(s == 'completed' for s in sub_statuses):
                    return  # Wait for subordinates to finish or start

            # Generate AI response
            if agent.type == 'manager':
                # Gather subordinate outputs if all are completed
                sub_outputs = []
                if agent.subordinates and all(self.agents[sub_id].status == 'completed' for sub_id in agent.subordinates if sub_id in self.agents):
                    for sub_id in agent.subordinates:
                        sub = self.agents.get(sub_id)
                        if sub:
                            sub_outputs.append(f"{sub.name} ({sub.role}):\n{sub.work_output.strip()}\n")
                    review_context = '\n'.join(sub_outputs)
                    prompt = f"Current project: {self.current_project}\n\nAll subordinates have completed their tasks. Here is their work:\n{review_context}\n\nAs project manager, review the work in the context of the overall app. If any changes or improvements are needed, output a new tasks.json code block assigning revision tasks. If everything is satisfactory, do not output a tasks.json block and state that the project is complete."
                else:
                    prompt = f"Current project: {self.current_project}\n\nAs a project manager, what are you working on right now? Consider your team's progress and what needs coordination. Be specific about your current management activities."
            else:
                prompt = f"Current task: {agent.current_task}\n\nWhat specific work are you doing right now? Describe your current progress and any technical details relevant to your role. If you are writing code, output it in markdown code blocks with the filename as the code block label (e.g., ```python main.py\ncode...\n```). You can output multiple files this way. When you are finished, state that you have completed your task."

            response = await anthropic_client.generate_response(
                agent.personality.system_prompt,
                prompt,
                max_tokens=agent.personality.max_tokens,
                temperature=agent.personality.temperature,
                agent_id=agent.id
            )

            # Update agent's work output
            timestamp = datetime.now().strftime('%H:%M:%S')
            agent.work_output += f"\n[{timestamp}] {response}"

            # --- New: Parse and write code files ---
            code_blocks_found = 0
            if self.project_dir:
                # Match code blocks with filename or language
                code_blocks = re.findall(r'```([\w.\-/]+)?\n([\s\S]*?)```', response)
                for fname, code in code_blocks:
                    if fname and '.' in fname:
                        fpath = os.path.join(self.project_dir, fname)
                        os.makedirs(os.path.dirname(fpath), exist_ok=True)
                        with open(fpath, 'w', encoding='utf-8') as f:
                            f.write(code.strip())
                        code_blocks_found += 1
                    elif fname:  # Only a language, not a filename
                        print(f"[Warning] Code block with language '{fname}' but no filename. Skipping.")
                    else:
                        print(f"[Warning] Code block with no filename or language. Skipping.")

            # If no code blocks were found for a worker, escalate to the manager
            if agent.type != 'manager' and code_blocks_found == 0:
                if agent.manager_id and agent.manager_id in self.agents:
                    self.send_message(agent.id, agent.manager_id, f"[ALERT] No code was produced for my task. Please review and assign corrections.", 'no_code_warning')
                    self.detailed_log.append({'event': 'no_code_warning', 'description': f'Agent {agent.name} produced no code for task: {agent.current_task}', 'timestamp': datetime.now().isoformat()})

            # After manager review, check the project directory for missing/incorrect files (basic: log if no files exist)
            if agent.type == 'manager' and self.project_dir and agent.subordinates and all(self.agents[sub_id].status == 'completed' for sub_id in agent.subordinates if sub_id in self.agents):
                files = []
                for root, dirs, fs in os.walk(self.project_dir):
                    for f in fs:
                        files.append(os.path.join(root, f))
                if not files:
                    self.detailed_log.append({'event': 'project_incomplete', 'description': 'No code files found in project directory after agent work. Manager should assign correction tasks.', 'timestamp': datetime.now().isoformat()})
                    print('[ALERT] No code files found in project directory after agent work. Manager should assign correction tasks.')

            # --- New: Parse and assign tasks from manager's response ---
            if agent.type == 'manager' and agent.subordinates:
                # Look for a tasks.json code block
                match = re.search(r'```tasks\.json\n([\s\S]*?)```', response)
                if match:
                    import json as _json
                    try:
                        tasks = _json.loads(match.group(1))
                        for sub_id in agent.subordinates:
                            sub = self.agents.get(sub_id)
                            if not sub:
                                continue
                            # Try to match by name, fallback to role
                            task = tasks.get(sub.name) or tasks.get(sub.role)
                            if task:
                                sub.current_task = task
                                sub.status = 'working'
                                # Optionally, send a message to the subordinate
                                self.send_message(agent.id, sub.id, f"New task assigned: {task}", 'task_assignment')
                                sub.work_output += f"\n[Manager requested revision at {timestamp}]"
                                # Clear previous output for revision
                                # sub.work_output = ''  # Optionally clear
                                sub.status = 'working'
                        # Set manager to idle until next review
                        agent.status = 'idle'
                    except Exception as e:
                        print(f"Error parsing tasks.json from manager: {e}")
                else:
                    # If no tasks.json and all subordinates completed, mark project as complete
                    if all(self.agents[sub_id].status == 'completed' for sub_id in agent.subordinates if sub_id in self.agents):
                        agent.status = 'completed'
                        self.increment_tasks_completed(agent) # Increment tasks completed
                        self.detailed_log.append({'event': 'project_completed', 'description': 'Project marked as complete by manager', 'timestamp': datetime.now().isoformat()})

            # --- Worker: If response indicates completion, set status to completed and notify manager ---
            if agent.type != 'manager' and agent.status == 'working':
                if re.search(r'completed|finished|done', response, re.IGNORECASE):
                    agent.status = 'completed'
                    self.increment_tasks_completed(agent) # Increment tasks completed
                    # Notify manager
                    if agent.manager_id and agent.manager_id in self.agents:
                        self.send_message(agent.id, agent.manager_id, f"Task completed. Output:\n{agent.work_output.strip()}", 'task_completed')

            # Agent might send messages based on their work
            await self.handle_agent_communication(agent, response)
            
        except Exception as e:
            print(f"Error processing work for agent {agent.name}: {e}")
            timestamp = datetime.now().strftime('%H:%M:%S')
            agent.work_output += f"\n[{timestamp}] [Error] Unable to process work: {str(e)}"

    def build_agent_context(self, agent: Agent) -> str:
        """Build context for the agent including project info, recent messages, and relevant file contents"""
        context = f"Project: {self.current_project}\n"
        context += f"Your current task: {agent.current_task}\n"

        # Add recent messages to/from this agent
        recent_messages = [msg for msg in self.global_messages[-5:] 
                          if msg['from_agent_id'] == agent.id or msg['to_agent_id'] == agent.id]
        if recent_messages:
            context += "Recent communications:\n"
            for msg in recent_messages:
                from_agent_obj = self.agents.get(msg['from_agent_id'])
                from_agent = getattr(from_agent_obj, 'name', 'Unknown') if from_agent_obj else 'Unknown'
                to_agent_obj = self.agents.get(msg['to_agent_id'])
                to_agent = getattr(to_agent_obj, 'name', 'Unknown') if to_agent_obj else 'Unknown'
                context += f"- {from_agent} → {to_agent}: {msg['content']}\n"

        # --- New: If the current_task mentions a file, include its contents ---
        if self.project_dir and agent.current_task:
            import re, os
            # Find all file-like words in the task
            file_pattern = r'([\w\-/]+\.[\w]+)'
            files_mentioned = re.findall(file_pattern, agent.current_task)
            files_added = set()
            for fname in files_mentioned:
                fpath = os.path.join(self.project_dir, fname)
                if os.path.isfile(fpath) and fname not in files_added:
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            file_content = f.read()
                        context += f"\nCurrent contents of {fname}:\n```{fname}\n{file_content}\n```\n"
                        files_added.add(fname)
                    except Exception as e:
                        context += f"\n[Could not read {fname}: {e}]\n"
        return context

    async def handle_agent_communication(self, agent: Agent, work_response: str):
        """Handle agent communication based on their work"""
        import random
        
        # Agents occasionally communicate based on their work
        if random.random() < 0.3:  # 30% chance to send a message
            
            if agent.type == 'manager' and agent.subordinates:
                # Manager sends updates to subordinates
                subordinate_id = random.choice(agent.subordinates)
                if subordinate_id in self.agents:
                    subordinate = self.agents[subordinate_id]
                    
                    prompt = f"You just completed this work: {work_response}\n\nSend a brief message to your team member {subordinate.name} ({subordinate.role}) about coordination, feedback, or next steps. Keep it short and professional."
                    
                    message_content = await anthropic_client.generate_response(
                        agent.personality.system_prompt,
                        prompt,
                        max_tokens=200,
                        temperature=0.8,
                        agent_id=agent.id
                    )
                    
                    self.send_message(agent.id, subordinate_id, message_content, 'coordination')
                    
            elif agent.manager_id and agent.manager_id in self.agents:
                # Worker sends updates to manager
                manager = self.agents[agent.manager_id]
                
                prompt = f"You just completed this work: {work_response}\n\nSend a brief status update to your manager {manager.name} about your progress, any blockers, or questions. Keep it short and professional."
                
                message_content = await anthropic_client.generate_response(
                    agent.personality.system_prompt,
                    prompt,
                    max_tokens=200,
                    temperature=0.8,
                    agent_id=agent.id
                )
                
                self.send_message(agent.id, agent.manager_id, message_content, 'status_update')

# Global system instance
system = MultiAgentSystem()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/agents', methods=['GET'])
def get_agents():
    return jsonify({
        'agents': {aid: agent.to_dict() for aid, agent in system.agents.items()},
        'system_running': system.system_running,
        'current_project': system.current_project
    })

@app.route('/api/agents', methods=['POST'])
def add_agent():
    data = request.get_json()
    agent_id = system.add_agent(
        data['name'],
        data['role'],
        data['type'],
        data['specialty'],
        data.get('manager_id')
    )
    
    socketio.emit('agent_added', system.agents[agent_id].to_dict())
    return jsonify({'success': True, 'agent_id': agent_id})

@app.route('/api/agents/<agent_id>', methods=['DELETE'])
def remove_agent(agent_id):
    success = system.remove_agent(agent_id)
    if success:
        socketio.emit('agent_removed', {'agent_id': agent_id})
    return jsonify({'success': success})

@app.route('/api/agents/<agent_id>/position', methods=['PUT'])
def update_agent_position(agent_id):
    data = request.get_json()
    if agent_id in system.agents:
        system.agents[agent_id].position = data['position']
        socketio.emit('agent_position_updated', {
            'agent_id': agent_id,
            'position': data['position']
        })
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/messages', methods=['GET'])
def get_messages():
    return jsonify({
        'messages': system.global_messages,
        'total': len(system.global_messages)
    })

@app.route('/api/messages', methods=['POST'])
def send_message():
    data = request.get_json()
    message = system.send_message(
        data['from_agent_id'],
        data['to_agent_id'],
        data['content'],
        data.get('type', 'communication')
    )
    
    socketio.emit('message_sent', message)
    return jsonify({'success': True, 'message': message})

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'api_key_configured': bool(ANTHROPIC_API_KEY and ANTHROPIC_API_KEY.strip()),
        'model': "claude-3-5-sonnet-20241022"
    })

@app.route('/api/project/start', methods=['POST'])
def start_project():
    data = request.get_json()
    system.start_project(data['description'])
    # Start agent work simulation in background
    if system.system_running:
        thread = threading.Thread(target=system.simulate_agent_work)
        thread.daemon = True
        thread.start()
    return jsonify({'success': True, 'project': system.current_project})

@app.route('/api/log', methods=['GET'])
def get_detailed_log():
    return jsonify({'log': system.detailed_log})

# --- User-to-Agent and User-to-Manager Communication & Task Assignment ---
@app.route('/api/agents/<agent_id>/assign_task', methods=['POST'])
def user_assign_task(agent_id):
    data = request.get_json()
    task = data.get('task')
    if agent_id in system.agents and task:
        agent = system.agents[agent_id]
        agent.current_task = task
        agent.status = 'working'
        # Log the manual assignment
        system.detailed_log.append({'event': 'user_assigned_task', 'description': f'User assigned task to {agent.name}: {task}', 'timestamp': datetime.now().isoformat()})
        socketio.emit('agents_updated', {
            'agents': {aid: a.to_dict() for aid, a in system.agents.items()},
            'messages': system.global_messages[-10:]
        })
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid agent or task'}), 400

@app.route('/api/agents/<agent_id>/user_message', methods=['POST'])
def user_message_agent(agent_id):
    data = request.get_json()
    content = data.get('content')
    if agent_id in system.agents and content:
        # User is represented as 'user' in from_agent_id
        system.send_message('user', agent_id, content, 'user_instruction')
        socketio.emit('message_sent', {
            'from_agent_id': 'user',
            'to_agent_id': agent_id,
            'content': content,
            'type': 'user_instruction',
            'timestamp': datetime.now().isoformat()
        })
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid agent or message'}), 400

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    emit('connected', {'data': 'Connected to Multi-Agent System'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# --- File tree and download endpoints ---
@app.route('/api/project/files', methods=['GET'])
def get_project_files():
    import os
    rel_path = request.args.get('path', '')
    abs_path = os.path.join(system.project_dir, rel_path) if system.project_dir else None
    if not abs_path or not abs_path.startswith(system.project_dir) or not os.path.exists(abs_path):
        return jsonify({'tree': []})
    def list_children(folder):
        tree = []
        for entry in os.scandir(folder):
            if entry.is_dir():
                tree.append({'type': 'folder', 'name': entry.name})
            else:
                tree.append({'type': 'file', 'name': entry.name})
        return tree
    return jsonify({'tree': list_children(abs_path)})

@app.route('/api/project/file', methods=['GET'])
def get_project_file():
    import os
    rel_path = request.args.get('path')
    if not rel_path:
        return jsonify({'error': 'No file path provided'}), 400
    abs_path = os.path.join(system.project_dir, rel_path)
    if not abs_path.startswith(system.project_dir) or not os.path.isfile(abs_path):
        return jsonify({'error': 'Invalid file path'}), 400
    with open(abs_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return jsonify({'content': content})

@app.route('/api/project/download', methods=['GET'])
def download_project_zip():
    import os
    import zipfile
    import io
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
    return send_file(mem_zip, mimetype='application/zip', as_attachment=True, download_name='project.zip')

# --- API endpoint for metrics ---
@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    return jsonify(system.get_metrics())

# --- Agent activation/deactivation endpoints ---
@app.route('/api/agents/<agent_id>/activate', methods=['POST'])
def activate_agent(agent_id):
    if agent_id in system.agents:
        system.agents[agent_id].is_active = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid agent'}), 400

@app.route('/api/agents/<agent_id>/deactivate', methods=['POST'])
def deactivate_agent(agent_id):
    if agent_id in system.agents:
        system.agents[agent_id].is_active = False
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid agent'}), 400

# --- Per-agent metrics endpoint ---
@app.route('/api/metrics/agents', methods=['GET'])
def get_agent_metrics():
    return jsonify({aid: {
        'name': a.name,
        'role': a.role,
        'status': a.status,
        'tasks_completed': getattr(a, 'tasks_completed', 0),
        'is_active': a.is_active
    } for aid, a in system.agents.items()})

if __name__ == '__main__':
    # Check API key configuration
    
    print("🚀 Starting Multi-Agent System...")
    print("📡 Access the application at: http://localhost:5000")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)