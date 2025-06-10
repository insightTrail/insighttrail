from flask import Flask, request, g, jsonify, render_template, Blueprint
import time
import os
import json
from .logger import setup_logger, log_request, log_error
from .metrics import record_metrics, get_metrics
from .traces import trace_request
import pkg_resources
import requests
import traceback
import sys
import uuid
from datetime import datetime
from werkzeug.wrappers import Request

class InsightTrailMiddleware:
    def __init__(self, app, log_file=None, log_level='INFO', max_file_size=1 * 1024 * 1024, backup_count=5,
                 enable_ui=True, url_prefix='/insight'):
        """
        Initialize InsightTrail middleware.

        Args:
            app: Flask application instance
            log_file: Path to log file. Defaults to 'insighttrail.log' in the parent directory of the app's root path.
            log_level: The logging level to use, e.g., 'INFO', 'DEBUG'.
            max_file_size: Maximum size of log file before rotation
            backup_count: Number of backup files to keep
            enable_ui: Whether to enable the web UI (default: True)
            url_prefix: URL prefix for InsightTrail routes (default: /insight)
        """
        self.app = app
        self.required_packages = self._load_required_packages(app.root_path)
        
        if log_file is None:
            # Default to a 'logs' directory in the parent of the app's root path
            app_parent_dir = os.path.dirname(app.root_path)
            log_file = os.path.join(app_parent_dir, 'logs', 'insighttrail.log')

        setup_logger(log_file, log_level, max_file_size, backup_count)
        self.log_file = log_file
        self._init_app(app)

        if enable_ui:
            self._setup_ui(url_prefix)

    def _load_required_packages(self, start_path):
        """
        Traverse up from start_path to find and parse a requirements.txt file.
        This helps identify the host application's dependencies.
        """
        current_path = start_path
        # Limit search to 5 levels up to avoid scanning the whole filesystem
        for _ in range(5):
            requirements_file = os.path.join(current_path, 'requirements.txt')
            if os.path.exists(requirements_file):
                try:
                    with open(requirements_file, 'r') as f:
                        packages = []
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                # Basic parsing: remove version specifiers and comments
                                package_name = line.split('#')[0].strip()
                                package_name = package_name.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].split('<')[0].split('>')[0].split('!=')[0].strip()
                                if package_name:
                                    packages.append(package_name.lower())
                        return packages
                except IOError:
                    return []  # Return empty list on read error
            
            parent = os.path.dirname(current_path)
            if parent == current_path:  # Reached the filesystem root
                break
            current_path = parent
            
        return []  # Return empty list if no requirements.txt is found

    def _get_package_info(self):
        """
        Gathers information about installed packages, highlighting those required
        by the host application and InsightTrail itself.
        """
        packages = []
        # Combine app's requirements with InsightTrail's key dependencies for highlighting
        insighttrail_deps = {'flask', 'waitress', 'psutil', 'requests'}
        app_deps = set(self.required_packages)
        required_set = app_deps.union(insighttrail_deps)

        for dist in pkg_resources.working_set:
            try:
                # Get package metadata
                package = {
                    'name': dist.key,
                    'current_version': dist.version,
                    'latest_version': dist.version,  # Will be updated if PyPI info is available
                    'required': dist.key.lower() in required_set,
                    'description': dist._get_metadata('Summary') if dist.has_metadata('Summary') else None
                }

                # Try to get latest version from PyPI
                try:
                    pypi_url = f"https://pypi.org/pypi/{dist.key}/json"
                    response = requests.get(pypi_url, timeout=2)
                    if response.status_code == 200:
                        pypi_data = response.json()
                        package['latest_version'] = pypi_data['info']['version']
                        if not package['description']:
                            package['description'] = pypi_data['info']['summary']
                except (requests.RequestException, KeyError, ValueError):
                    pass

                packages.append(package)
            except Exception:
                continue

        # Sort packages: required first, then alphabetically
        return sorted(packages, key=lambda x: (not x['required'], x['name'].lower()))

    def _init_app(self, app):
        @app.before_request
        def before_request():
            g.start_time = time.time()
            trace_request(request)

        @app.after_request
        def after_request(response):
            duration = time.time() - g.start_time
            record_metrics(request, response, duration)
            log_request(request, response, duration)
            return response

        @app.teardown_request
        def teardown_request(exception=None):
            if exception is not None:
                duration = time.time() - g.start_time
                log_error(request, exception, duration)

    def _parse_log_file(self):
        logs = []
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line)
                        # Convert timestamp to datetime for sorting
                        log_entry['request_time'] = datetime.strptime(log_entry['timestamp'], '%Y-%m-%dT%H:%M:%S.%f')
                        logs.append(log_entry)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        print(f"Error parsing log line: {e}")
                        continue
            
            # Sort logs in descending order by request_time
            logs.sort(key=lambda log: log['request_time'], reverse=True)
            return logs
        except Exception as e:
            print(f"Error reading log file: {e}")
            return []

    def _setup_ui(self, url_prefix):
        # Create a blueprint for InsightTrail UI
        insight_bp = Blueprint('insighttrail', __name__,
                               template_folder='templates',
                               static_folder='static',
                               url_prefix=url_prefix)

        @insight_bp.route('/')
        def index():
            return render_template("index.html")

        @insight_bp.route('/api/packages')
        def get_packages():
            return jsonify(self._get_package_info())

        @insight_bp.route('/api/logs')
        def get_logs():
            try:
                # Return all logs in JSON format
                logs = self._parse_log_file()
                return jsonify(logs)
            except Exception as e:
                print(f"Error in get_logs: {e}")
                return jsonify({"error": str(e)}), 500

        @insight_bp.route('/api/analytics/logs', methods=['GET'])
        def fetch_logs():
            try:
                logs = self._parse_log_file()
                metrics = get_metrics()
                return jsonify({
                    'logs': logs,
                    'metrics': metrics
                })
            except Exception as e:
                print(f"Error in fetch_logs: {e}")
                return jsonify({"error": str(e)}), 500

        @insight_bp.route('/api/analytics/search', methods=['GET'])
        def search_by_trace_id():
            try:
                trace_id = request.args.get('trace_id')
                logs = self._parse_log_file()
                result = [log for log in logs if log.get("trace_id") == trace_id]
                metrics = get_metrics()
                return jsonify({
                    'logs': result,
                    'metrics': metrics
                })
            except Exception as e:
                print(f"Error in search_by_trace_id: {e}")
                return jsonify({"error": str(e)}), 500

        # Register the blueprint with the main app
        self.app.register_blueprint(insight_bp)

    def _get_code_context(self, filename, line_number, context_lines=5):
        """Get the code context around the error line."""
        try:
            if not os.path.exists(filename):
                return None

            with open(filename, 'r', encoding='utf-8') as file:
                lines = file.readlines()
                
            start = max(0, line_number - context_lines - 1)
            end = min(len(lines), line_number + context_lines)
            
            return {
                'lines': [line.rstrip('\n') for line in lines[start:end]],
                'start_line': start + 1,
                'error_line': line_number,
                'filename': filename
            }
        except Exception as e:
            print(f"Error getting code context: {e}")
            return None

    def _log_error(self, error, request=None):
        """Log an error with full traceback and context."""
        frames = []
        tb = error.__traceback__
        
        while tb is not None:
            filename = tb.tb_frame.f_code.co_filename
            function = tb.tb_frame.f_code.co_name
            line_number = tb.tb_lineno
            
            # Get code context for this frame
            context = self._get_code_context(filename, line_number)
            
            # Get local variables (excluding special vars and functions)
            local_vars = {}
            for key, value in tb.tb_frame.f_locals.items():
                if not key.startswith('__') and not callable(value):
                    try:
                        # Try to convert value to string, fallback to type name if fails
                        local_vars[key] = str(value)
                    except:
                        local_vars[key] = f"<{type(value).__name__}>"

            frame_info = {
                'filename': filename,
                'function': function,
                'line': line_number,
                'context': context,
                'locals': local_vars
            }
            frames.append(frame_info)
            tb = tb.tb_next

        error_info = {
            'type': error.__class__.__name__,
            'message': str(error),
            'frames': frames,
            'traceback': ''.join(traceback.format_exception(type(error), error, error.__traceback__)),
            'context': {
                'module': getattr(error, '__module__', 'unknown'),
                'doc': getattr(error, '__doc__', None),
                'args': getattr(error, 'args', None),
            }
        }

        if request:
            error_info['context'].update({
                'url': request.path,
                'method': request.method,
                'headers': dict(request.headers),
                'params': dict(request.args)
            })

        return error_info

    def __call__(self, environ, start_response):
        """WSGI middleware entry point."""
        request = Request(environ)
        start_time = time.time()
        
        try:
            response = self.app(environ, start_response)
            status_code = int(response[0].decode().split()[0])
            
            # Process response and gather metrics
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            
            log_entry = {
                'timestamp': datetime.utcnow().isoformat(),
                'trace_id': getattr(g, 'trace_id', str(uuid.uuid4())),
                'request': {
                    'method': request.method,
                    'path': request.path,
                    'client': request.remote_addr,
                    'user_agent': request.user_agent.string,
                    'status': status_code,
                    'duration_ms': duration_ms,
                    'query_params': dict(request.args)
                },
                'runtime': self._get_runtime_info(),
                'system': self._get_system_metrics()
            }
            
            # Only add error info for error status codes
            if status_code >= 400:
                log_entry['error'] = self._log_error(
                    Exception(f"HTTP {status_code}"),
                    request
                )
            
            self._write_log(log_entry)
            return response
            
        except Exception as e:
            # Handle uncaught exceptions
            error_info = self._log_error(e, request)
            
            log_entry = {
                'timestamp': datetime.utcnow().isoformat(),
                'trace_id': getattr(g, 'trace_id', str(uuid.uuid4())),
                'request': {
                    'method': request.method,
                    'path': request.path,
                    'client': request.remote_addr,
                    'user_agent': request.user_agent.string,
                    'status': 500,
                    'duration_ms': (time.time() - start_time) * 1000,
                    'query_params': dict(request.args)
                },
                'runtime': self._get_runtime_info(),
                'system': self._get_system_metrics(),
                'error': error_info
            }
            
            self._write_log(log_entry)
            
            # Return a 500 error response
            response_body = json.dumps({
                'error': 'Internal Server Error',
                'message': str(e)
            }).encode('utf-8')
            
            response_headers = [
                ('Content-Type', 'application/json'),
                ('Content-Length', str(len(response_body)))
            ]
            
            start_response('500 Internal Server Error', response_headers)
            return [response_body]
