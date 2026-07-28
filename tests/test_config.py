import os
import yaml
import pytest
from insighttrail.config import (
    DEFAULT_CONFIG,
    load_config,
    _discover_config_path,
    validate_config,
)


class TestDefaultConfig:
    def test_all_keys_present(self):
        assert isinstance(DEFAULT_CONFIG, dict)
        expected_keys = [
            'log_file', 'log_level', 'max_file_size', 'backup_count',
            'log_storage', 'db_config',
            'enable_ui', 'url_prefix', 'capture_runtime',
            'capture_system_metrics', 'capture_env_vars', 'env_allowlist',
            'dependency_check', 'ultra_light_mode', 'enable_charts',
            'ui_refresh_seconds', 'track_internal_requests',
            'async_logging', 'log_queue_size', 'success_log_sample_rate',
            'slow_request_threshold_ms', 'dependency_cache_ttl_seconds',
            'dependency_async_refresh', 'dependency_request_timeout',
            'enable_excel_reports', 'report_max_rows', 'report_timezone',
            'color_scheme', 'dark_mode',
        ]
        for key in expected_keys:
            assert key in DEFAULT_CONFIG, f"Missing key: {key}"

    def test_defaults_match_previous(self):
        assert DEFAULT_CONFIG['log_level'] == 'INFO'
        assert DEFAULT_CONFIG['enable_ui'] is True
        assert DEFAULT_CONFIG['url_prefix'] == '/insight'
        assert DEFAULT_CONFIG['capture_runtime'] is False
        assert DEFAULT_CONFIG['ultra_light_mode'] is False
        assert DEFAULT_CONFIG['async_logging'] is True
        assert DEFAULT_CONFIG['log_queue_size'] == 5000
        assert DEFAULT_CONFIG['color_scheme'] == 'orange'
        assert DEFAULT_CONFIG['dark_mode'] is False
        assert DEFAULT_CONFIG['log_storage'] == 'file'


class TestLoadConfig:
    def test_no_file_raises(self):
        with pytest.raises(ValueError, match='Failed to load config'):
            load_config(config_path='/nonexistent/path/config.yaml')

    def test_explicit_yaml_overrides(self, tmp_path):
        yaml_file = tmp_path / 'test_config.yaml'
        yaml_content = """
insighttrail:
  log_level: DEBUG
  enable_ui: false
  color_scheme: catppuccin
  dark_mode: true
"""
        yaml_file.write_text(yaml_content)
        cfg = load_config(config_path=str(yaml_file))
        assert cfg['log_level'] == 'DEBUG'
        assert cfg['enable_ui'] is False
        assert cfg['color_scheme'] == 'catppuccin'
        assert cfg['dark_mode'] is True
        assert cfg['max_file_size'] == DEFAULT_CONFIG['max_file_size']

    def test_partial_yaml(self, tmp_path):
        yaml_file = tmp_path / 'partial.yaml'
        yaml_file.write_text("insighttrail:\n  log_level: WARN\n")
        cfg = load_config(config_path=str(yaml_file))
        assert cfg['log_level'] == 'WARN'
        assert cfg['backup_count'] == DEFAULT_CONFIG['backup_count']

    def test_flat_yaml_no_insighttrail_key(self, tmp_path):
        yaml_file = tmp_path / 'flat.yaml'
        yaml_file.write_text("log_level: ERROR\n")
        cfg = load_config(config_path=str(yaml_file))
        assert cfg['log_level'] == 'ERROR'

    def test_none_values_ignored(self, tmp_path):
        yaml_file = tmp_path / 'none_vals.yaml'
        yaml_file.write_text("insighttrail:\n  log_level: ~\n")
        cfg = load_config(config_path=str(yaml_file))
        assert cfg['log_level'] == DEFAULT_CONFIG['log_level']

    def test_validation_rejects_invalid_scheme(self, tmp_path):
        yaml_file = tmp_path / 'bad_scheme.yaml'
        yaml_file.write_text("insighttrail:\n  color_scheme: invalid\n")
        with pytest.raises(ValueError, match='color_scheme'):
            load_config(config_path=str(yaml_file))

    def test_validation_rejects_bad_dark_mode(self, tmp_path):
        yaml_file = tmp_path / 'bad_dark.yaml'
        yaml_file.write_text("insighttrail:\n  dark_mode: maybe\n")
        with pytest.raises(ValueError, match='dark_mode'):
            load_config(config_path=str(yaml_file))

    def test_invalid_yaml_raises(self, tmp_path):
        yaml_file = tmp_path / 'invalid.yaml'
        yaml_file.write_text("invalid: yaml: : : broken\n")
        with pytest.raises(ValueError, match='Failed to load config'):
            load_config(config_path=str(yaml_file))


class TestValidateConfig:
    def test_valid_config_passes(self):
        validate_config(DEFAULT_CONFIG)

    def test_bad_ui_refresh(self):
        with pytest.raises(ValueError, match='ui_refresh_seconds'):
            validate_config({'ui_refresh_seconds': 1})

    def test_bad_log_queue_size(self):
        with pytest.raises(ValueError, match='log_queue_size'):
            validate_config({'log_queue_size': 50, 'max_file_size': 1048576, 'report_max_rows': 200000, 'backup_count': 5, 'success_log_sample_rate': 1.0, 'dependency_cache_ttl_seconds': 21600, 'dependency_request_timeout': 2, 'color_scheme': 'orange', 'dark_mode': False, 'ui_refresh_seconds': 10})

    def test_bad_sample_rate(self):
        with pytest.raises(ValueError, match='success_log_sample_rate'):
            validate_config({'success_log_sample_rate': 1.5, 'max_file_size': 1048576, 'report_max_rows': 200000, 'backup_count': 5, 'dependency_cache_ttl_seconds': 21600, 'dependency_request_timeout': 2, 'color_scheme': 'orange', 'dark_mode': False, 'ui_refresh_seconds': 10, 'log_queue_size': 5000})

    def test_monochrome_scheme_is_valid(self):
        validate_config({'color_scheme': 'monochrome'})

    def test_invalid_log_storage_rejected(self):
        with pytest.raises(ValueError, match='log_storage'):
            validate_config({'log_storage': 'remote'})

    def test_boundary_values_are_valid(self):
        validate_config({
            'ui_refresh_seconds': 2,
            'log_queue_size': 100,
            'max_file_size': 1,
            'report_max_rows': 1000,
            'backup_count': 0,
            'success_log_sample_rate': 0.0,
            'dependency_cache_ttl_seconds': 60,
            'dependency_request_timeout': 1,
        })

    def test_yaml_loads_storage_configuration(self, tmp_path):
        yaml_file = tmp_path / 'storage.yaml'
        yaml_file.write_text('insighttrail:\n  log_storage: db\n  db_config:\n    url: sqlite:///logs.db\n')
        cfg = load_config(config_path=str(yaml_file))
        assert cfg['log_storage'] == 'db'
        assert cfg['db_config']['url'] == 'sqlite:///logs.db'


class TestDiscoverConfigPath:
    def test_no_file_returns_none(self):
        assert _discover_config_path() is None
