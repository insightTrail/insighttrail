import os
import yaml

DEFAULT_CONFIG = {
    'log_file': None,
    'log_level': 'INFO',
    'max_file_size': 1048576,
    'backup_count': 5,
    'enable_ui': True,
    'url_prefix': '/insight',
    'capture_runtime': False,
    'capture_system_metrics': False,
    'capture_env_vars': False,
    'env_allowlist': [],
    'dependency_check': None,
    'ultra_light_mode': False,
    'enable_charts': None,
    'ui_refresh_seconds': 10,
    'track_internal_requests': False,
    'async_logging': True,
    'log_queue_size': 5000,
    'success_log_sample_rate': 1.0,
    'slow_request_threshold_ms': None,
    'dependency_cache_ttl_seconds': 21600,
    'dependency_async_refresh': True,
    'dependency_request_timeout': 2,
    'enable_excel_reports': True,
    'report_max_rows': 200000,
    'report_timezone': 'UTC',
    'color_scheme': 'orange',
    'dark_mode': False,
}


def _discover_config_path():
    search_paths = [
        os.path.join(os.getcwd(), 'insighttrail.yaml'),
        os.path.join(os.getcwd(), 'insighttrail.yml'),
        os.path.expanduser('~/.config/insighttrail/config.yaml'),
        os.path.expanduser('~/.config/insighttrail/config.yml'),
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return None


def validate_config(config):
    errors = []
    if config.get('ui_refresh_seconds', 10) < 2:
        errors.append('ui_refresh_seconds must be >= 2')
    if config.get('log_queue_size', 5000) < 100:
        errors.append('log_queue_size must be >= 100')
    if config.get('max_file_size', 1048576) <= 0:
        errors.append('max_file_size must be > 0')
    if config.get('report_max_rows', 200000) < 1000:
        errors.append('report_max_rows must be >= 1000')
    if config.get('backup_count', 5) < 0:
        errors.append('backup_count must be >= 0')
    if not (0.0 <= config.get('success_log_sample_rate', 1.0) <= 1.0):
        errors.append('success_log_sample_rate must be between 0.0 and 1.0')
    if config.get('dependency_cache_ttl_seconds', 21600) < 60:
        errors.append('dependency_cache_ttl_seconds must be >= 60')
    if config.get('dependency_request_timeout', 2) < 1:
        errors.append('dependency_request_timeout must be >= 1')
    scheme = config.get('color_scheme', 'orange')
    if scheme not in ('orange', 'catppuccin'):
        errors.append("color_scheme must be 'orange' or 'catppuccin'")
    dm = config.get('dark_mode', False)
    if dm not in (True, False, 'auto'):
        errors.append("dark_mode must be true, false, or 'auto'")
    if errors:
        raise ValueError('Config validation errors: ' + '; '.join(errors))


def load_config(config_path=None):
    config = dict(DEFAULT_CONFIG)

    path = config_path or _discover_config_path()
    if path is not None:
        try:
            with open(path, 'r') as f:
                yaml_data = yaml.safe_load(f)
            if isinstance(yaml_data, dict):
                insighttrail_data = yaml_data.get('insighttrail', yaml_data)
                if isinstance(insighttrail_data, dict):
                    for key in list(config.keys()):
                        if key in insighttrail_data and insighttrail_data[key] is not None:
                            config[key] = insighttrail_data[key]
        except (yaml.YAMLError, IOError) as e:
            raise ValueError(f"Failed to load config from {path}: {e}")

    validate_config(config)
    return config