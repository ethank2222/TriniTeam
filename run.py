#!/usr/bin/env python3
"""
One-Command Setup Script for Self-Contained Multi-Agent System
No databases required - only Anthropic API
"""

import os
import sys
import subprocess
import urllib.request
import json
from pathlib import Path

def print_banner():
    """Print setup banner"""
    print("\n" + "="*60)
    print("🚀 Self-Contained Multi-Agent System Setup")
    print("="*60)
    print("📦 No databases required")
    print("🌐 Only connects to Anthropic API")
    print("⚡ Complete setup in under 2 minutes")
    print("="*60 + "\n")

def check_python_version():
    """Check Python version"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ required")
        print(f"   Current version: {sys.version}")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")

def check_pip():
    """Check if pip is available"""
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"], 
                      capture_output=True, check=True)
        print("✅ pip is available")
    except subprocess.CalledProcessError:
        print("❌ pip is not available")
        print("   Please install pip first")
        sys.exit(1)

def create_virtual_environment():
    """Create virtual environment"""
    venv_path = Path("venv")
    
    if venv_path.exists():
        print("📦 Virtual environment already exists")
        return
    
    print("📦 Creating virtual environment...")
    try:
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
        print("✅ Virtual environment created")
    except subprocess.CalledProcessError:
        print("❌ Failed to create virtual environment")
        sys.exit(1)

def get_pip_command():
    """Get pip command for the virtual environment"""
    if sys.platform == "win32":
        return str(Path("venv") / "Scripts" / "pip")
    else:
        return str(Path("venv") / "bin" / "pip")

def install_dependencies():
    """Install dependencies"""
    print("📦 Installing dependencies...")
    
    # Create minimal requirements.txt if it doesn't exist
    requirements_content = """Flask==2.3.3
Flask-SocketIO==5.3.6
python-socketio==5.9.0
python-engineio==4.7.1
aiohttp==3.9.1
python-dotenv==1.0.0
gunicorn==21.2.0
eventlet==0.33.3
"""
    
    if not Path("requirements.txt").exists():
        with open("requirements.txt", "w") as f:
            f.write(requirements_content)
        print("✅ Created requirements.txt")
    
    pip_cmd = get_pip_command()
    try:
        subprocess.run([pip_cmd, "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ Dependencies installed")
    except subprocess.CalledProcessError as e:
        print("❌ Failed to install dependencies")
        print(f"   Error: {e}")
        sys.exit(1)

def create_env_file():
    """Create .env file"""
    env_path = Path(".env")
    
    if env_path.exists():
        print("🔧 .env file already exists")
        return
    
    print("🔧 Creating .env file...")
    
    # Get API key from user
    api_key = input("Enter your Anthropic API key (or press Enter to skip): ").strip()
    
    env_content = f"""# Multi-Agent System Configuration
ANTHROPIC_API_KEY={api_key}
SECRET_KEY=dev-secret-key-change-in-production
DEBUG=True
HOST=0.0.0.0
PORT=5000
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT=30
LOG_LEVEL=INFO
"""
    
    with open(".env", "w") as f:
        f.write(env_content)
    
    print("✅ .env file created")
    
    if not api_key:
        print("⚠️  Remember to add your ANTHROPIC_API_KEY to .env")

def create_directories():
    """Create necessary directories"""
    dirs = ["static/css", "static/js", "templates", "logs"]
    
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
    
    print("✅ Directories created")

def test_installation():
    """Test the installation"""
    print("🧪 Testing installation...")
    
    try:
        # Test imports
        test_script = """
import flask
import flask_socketio
import aiohttp
import dotenv
print("✅ All imports successful")
"""
        
        python_cmd = str(Path("venv") / ("Scripts" if sys.platform == "win32" else "bin") / "python")
        result = subprocess.run([python_cmd, "-c", test_script], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Installation test passed")
        else:
            print("❌ Installation test failed")
            print(f"   Error: {result.stderr}")
    
    except Exception as e:
        print(f"❌ Installation test failed: {e}")

def print_next_steps():
    """Print next steps"""
    print("\n" + "="*60)
    print("🎉 Setup Complete!")
    print("="*60)
    print("Next steps:")
    print()
    
    if sys.platform == "win32":
        print("1. Activate virtual environment:")
        print("   venv\\Scripts\\activate")
        print()
        print("2. Start the system:")
        print("   python run.py")
    else:
        print("1. Activate virtual environment:")
        print("   source venv/bin/activate")
        print()
        print("2. Start the system:")
        print("   python run.py")
    
    print()
    print("3. Open your browser:")
    print("   http://localhost:5000")
    print()
    print("4. Start building!")
    print("   - Describe your project")
    print("   - Watch AI agents build it")
    print("   - Download the result")
    print()
    print("💡 Tips:")
    print("   - Make sure your .env has ANTHROPIC_API_KEY")
    print("   - No databases needed - everything in memory")
    print("   - Download projects before stopping")
    print("="*60 + "\n")

def main():
    """Main setup function"""
    print_banner()
    
    # Check system requirements
    check_python_version()
    check_pip()
    
    # Setup environment
    create_virtual_environment()
    install_dependencies()
    create_env_file()
    create_directories()
    
    # Test installation
    test_installation()
    
    # Show next steps
    print_next_steps()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1)