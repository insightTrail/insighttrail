# InsightTrail

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![Flask Version](https://img.shields.io/badge/flask-2.x%2B-green.svg)](https://flask.palletsprojects.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview
InsightTrail is a powerful yet lightweight observability middleware for Flask applications. It provides comprehensive logging, real-time metrics, and request tracing out of the box. Designed for developers who need to monitor, debug, and gain insights into their Flask microservices with minimal setup.

With its clean web UI, you can visualize analytics, inspect logs, and track down issues without leaving your browser.

## Key Features
- 🔍 **Request & Error Tracing**: Automatically generate unique trace IDs for each request and trace errors with full context.
- 📊 **Real-time Analytics UI**: A built-in web dashboard to visualize key metrics, inspect logs, and analyze application performance.
- 📝 **Structured JSON Logging**: Smart, structured logging with configurable log levels and automatic log rotation.
- 🚀 **Performance Metrics**: Capture response times, CPU/memory usage, and other system-level metrics for each request.
- 📦 **Dependency Tracking**: Monitor your project's dependencies and check for the latest versions.
- ✅ **Sensible Defaults**: Works out of the box with sane defaults, requiring no initial configuration.
- ⚙️ **Highly Configurable**: Customize logging, log file paths, UI access, and more to fit your needs.

## Installation

```bash
pip install insighttrail
```

Or install from source:

```bash
# Replace with your repository URL
git clone https://github.com/your-username/insighttrail.git
cd insighttrail
pip install -e .
```

## Quick Start

### Basic Usage
Simply wrap your Flask app with the `InsightTrailMiddleware`. It will automatically start logging to a file in your project's parent directory and enable the web UI.

```python
from flask import Flask
from insighttrail import InsightTrailMiddleware

app = Flask(__name__)

# Initialize InsightTrail with default settings
# Logs will be stored in ../logs/insighttrail.log
# The UI will be available at /insight
middleware = InsightTrailMiddleware(app)

@app.route('/')
def hello():
    return 'Hello, World!'

if __name__ == '__main__':
    app.run()
```
After running your app, navigate to `/insight` to view the analytics dashboard.

### Advanced Configuration
You can customize InsightTrail's behavior by passing parameters to the middleware.

```python
from flask import Flask
from insighttrail import InsightTrailMiddleware

app = Flask(__name__)

# Initialize InsightTrail with custom settings
middleware = InsightTrailMiddleware(
    app,
    log_file='path/to/your/logs/app.log',
    log_level='DEBUG',
    max_file_size=5 * 1024 * 1024,  # 5MB
    backup_count=10,
    enable_ui=True,
    url_prefix='/monitoring' # Access the UI at /monitoring
)
```

## Web UI
InsightTrail comes with a built-in web interface to visualize the data it collects. By default, it's available at the `/insight` endpoint of your application.

The UI provides:
- **Real-time Metrics**: View total requests, error rates, and average response times.
- **Log Viewer**: Search, filter, and inspect detailed, structured logs.
- **Error Analysis**: Examine exceptions with full stack traces and request context.
- **System Health**: Monitor CPU, memory, and disk usage.

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `log_file` | str | `None` | Path to the log file. If `None`, defaults to `logs/insighttrail.log` in the parent directory of the app's root path. |
| `log_level` | str | `'INFO'` | Minimum log level to capture (e.g., `'DEBUG'`, `'INFO'`, `'WARNING'`). |
| `max_file_size` | int | `1048576` (1MB) | Maximum size of the log file in bytes before rotation. |
| `backup_count` | int | `5` | Number of backup log files to keep. |
| `enable_ui` | bool | `True` | Enable or disable the web UI. |
| `url_prefix` | str | `'/insight'` | The URL prefix for the web UI endpoint. |

## Log Output Format
InsightTrail generates structured JSON logs, making them easy to parse and analyze.

```json
{
    "trace_id": "a7b1c2d3-e4f5-g6h7-i8j9-k0l1m2n3o4p5",
    "timestamp": "2024-07-29T12:34:56.789012",
    "level": "INFO",
    "request": {
        "method": "GET",
        "path": "/api/users",
        "status": 200,
        "duration_ms": 45.67,
        "client": "127.0.0.1"
    },
    "runtime": { "...": "..." },
    "system": { "...": "..." }
}
```

## Requirements

- Python 3.7 or higher
- Flask 2.x or higher
- Additional dependencies:
  - blinker
  - psutil
  - werkzeug

## Contributing
Contributions are welcome! If you have a feature request, bug report, or want to improve the code, please feel free to submit an issue or a pull request.

## License
This project is licensed under the MIT License.

## Support
For support, please create an issue in the project's GitHub repository.