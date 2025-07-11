"""
Enhanced Multi-Agent System Configuration
"""
import os
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base configuration class"""
    
    # Core Settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # API Configuration
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')  # Alternative AI provider
    
    # Database Configuration
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///multiagent.db'
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis Configuration (for caching and session storage)
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = REDIS_URL
    
    # File Storage
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Logging Configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Performance Settings
    MAX_CONCURRENT_REQUESTS = int(os.environ.get('MAX_CONCURRENT_REQUESTS', '10'))
    REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '30'))
    CACHE_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT', '300'))
    
    # Agent Configuration
    MAX_AGENTS = int(os.environ.get('MAX_AGENTS', '20'))
    DEFAULT_AGENT_TIMEOUT = int(os.environ.get('DEFAULT_AGENT_TIMEOUT', '300'))
    MAX_TASK_RETRIES = int(os.environ.get('MAX_TASK_RETRIES', '3'))
    
    # Security Settings
    RATE_LIMIT_ENABLED = os.environ.get('RATE_LIMIT_ENABLED', 'True').lower() == 'true'
    RATE_LIMIT_PER_MINUTE = int(os.environ.get('RATE_LIMIT_PER_MINUTE', '60'))
    
    # Monitoring
    METRICS_ENABLED = os.environ.get('METRICS_ENABLED', 'True').lower() == 'true'
    PERFORMANCE_MONITORING = os.environ.get('PERFORMANCE_MONITORING', 'True').lower() == 'true'
    
    # WebSocket Configuration
    SOCKETIO_ASYNC_MODE = 'threading'
    SOCKETIO_CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ORIGINS', '*').split(',')
    
    @staticmethod
    def init_app(app):
        """Initialize application with configuration"""
        pass

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False
    
    # More verbose logging in development
    LOG_LEVEL = 'DEBUG'
    
    # Lower limits for development
    MAX_CONCURRENT_REQUESTS = 5
    MAX_AGENTS = 10
    
    # Disable caching in development
    CACHE_TYPE = 'null'

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    
    # Stricter security in production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Production optimizations
    MAX_CONCURRENT_REQUESTS = 20
    CACHE_TIMEOUT = 600  # 10 minutes
    
    # Enable all monitoring
    METRICS_ENABLED = True
    PERFORMANCE_MONITORING = True
    
    @staticmethod
    def init_app(app):
        """Production-specific initialization"""
        # Log to stderr in production
        import logging
        from logging import StreamHandler
        
        handler = StreamHandler()
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Multi-Agent System startup')

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = False
    
    # Use in-memory database for testing
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
    # Disable caching for testing
    CACHE_TYPE = 'null'
    
    # Faster timeouts for testing
    REQUEST_TIMEOUT = 5
    DEFAULT_AGENT_TIMEOUT = 10
    
    # Disable external API calls in testing
    ANTHROPIC_API_KEY = 'test-key'

# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

# Agent-specific configuration
AGENT_CONFIGS = {
    'manager': {
        'max_tokens': 2000,
        'temperature': 0.6,
        'timeout': 60,
        'max_retries': 3
    },
    'worker': {
        'max_tokens': 1500,
        'temperature': 0.7,
        'timeout': 45,
        'max_retries': 3
    },
    'specialist': {
        'max_tokens': 2500,
        'temperature': 0.5,
        'timeout': 90,
        'max_retries': 2
    }
}

# Performance thresholds
PERFORMANCE_THRESHOLDS = {
    'response_time': {
        'excellent': 1.0,
        'good': 2.0,
        'acceptable': 5.0,
        'poor': 10.0
    },
    'success_rate': {
        'excellent': 0.95,
        'good': 0.90,
        'acceptable': 0.85,
        'poor': 0.80
    },
    'cache_hit_rate': {
        'excellent': 0.80,
        'good': 0.60,
        'acceptable': 0.40,
        'poor': 0.20
    }
}

# Project templates
PROJECT_TEMPLATES = {
    'web-app': {
        'name': 'Web Application',
        'description': 'Create a modern web application with React frontend and Flask backend',
        'technologies': ['React', 'TypeScript', 'Flask', 'SQLAlchemy', 'CSS3'],
        'structure': {
            'frontend/': ['src/', 'public/', 'tests/'],
            'backend/': ['app/', 'tests/', 'migrations/'],
            'docs/': ['README.md', 'API.md']
        }
    },
    'api': {
        'name': 'REST API',
        'description': 'Build a RESTful API with authentication and documentation',
        'technologies': ['Flask', 'SQLAlchemy', 'JWT', 'Swagger'],
        'structure': {
            'app/': ['models/', 'routes/', 'utils/', 'middleware/'],
            'tests/': ['test_models.py', 'test_routes.py'],
            'docs/': ['API.md', 'swagger.yaml']
        }
    },
    'dashboard': {
        'name': 'Analytics Dashboard',
        'description': 'Create an interactive dashboard with charts and real-time data',
        'technologies': ['React', 'Chart.js', 'WebSockets', 'Flask', 'Redis'],
        'structure': {
            'frontend/': ['src/components/', 'src/pages/', 'src/charts/'],
            'backend/': ['app/api/', 'app/websocket/', 'app/data/'],
            'data/': ['schemas/', 'migrations/']
        }
    },
    'mobile': {
        'name': 'Mobile App',
        'description': 'Build a cross-platform mobile application',
        'technologies': ['React Native', 'TypeScript', 'Redux', 'Firebase'],
        'structure': {
            'src/': ['screens/', 'components/', 'navigation/', 'services/'],
            'assets/': ['images/', 'fonts/'],
            'tests/': ['__tests__/']
        }
    }
}

# Validation rules
VALIDATION_RULES = {
    'agent_name': {
        'min_length': 3,
        'max_length': 50,
        'pattern': r'^[a-zA-Z0-9_-]+$'
    },
    'project_description': {
        'min_length': 10,
        'max_length': 5000
    },
    'message_content': {
        'min_length': 1,
        'max_length': 10000
    }
}

def get_config(config_name: str = None) -> Config:
    """Get configuration based on environment"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')
    
    return config.get(config_name, config['default'])

def validate_config() -> Dict[str, Any]:
    """Validate configuration and return status"""
    issues = []
    
    # Check required API keys
    if not Config.ANTHROPIC_API_KEY:
        issues.append('ANTHROPIC_API_KEY is not set')
    
    # Check database connectivity
    if Config.DATABASE_URL.startswith('sqlite:'):
        if not os.path.exists(os.path.dirname(Config.DATABASE_URL.replace('sqlite:///', ''))):
            issues.append('SQLite database directory does not exist')
    
    # Check Redis connectivity (if enabled)
    if Config.CACHE_TYPE == 'redis':
        try:
            import redis
            r = redis.from_url(Config.REDIS_URL)
            r.ping()
        except Exception as e:
            issues.append(f'Redis connection failed: {str(e)}')
    
    # Check file permissions
    if not os.path.exists(Config.UPLOAD_FOLDER):
        try:
            os.makedirs(Config.UPLOAD_FOLDER)
        except Exception as e:
            issues.append(f'Cannot create upload folder: {str(e)}')
    
    return {
        'valid': len(issues) == 0,
        'issues': issues
    }

# Environment-specific settings
if __name__ == '__main__':
    # Configuration validation
    status = validate_config()
    if status['valid']:
        print("✅ Configuration is valid")
    else:
        print("❌ Configuration issues found:")
        for issue in status['issues']:
            print(f"  - {issue}")