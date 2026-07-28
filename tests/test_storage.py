import datetime
import json

from insighttrail.storage import (
    FileLogStore,
    _coerce_value,
    _parse_datetime,
    create_log_store,
    get_source_value,
    normalize_db_config,
)


def _entry(trace_id, timestamp):
    return {
        'trace_id': trace_id,
        'timestamp': timestamp,
        'level': 'INFO',
        'request': {
            'method': 'GET', 'path': f'/{trace_id}', 'status': 200,
            'duration_ms': 1.5, 'client': '127.0.0.1',
        },
    }


class TestFileLogStore:
    def test_reads_json_lines_and_paginates(self, tmp_path):
        log_file = tmp_path / 'insighttrail.log'
        log_file.write_text('\n'.join(
            json.dumps(_entry(str(i), f'2026-01-0{i}T00:00:00'))
            for i in range(1, 4)
        ) + '\n')
        store = FileLogStore(str(log_file))

        page = store.get_page(limit=2)
        assert [item['trace_id'] for item in page['logs']] == ['2', '3']
        assert page['has_more'] is True
        next_page = store.get_page(limit=2, cursor=page['cursor'])
        assert next_page['logs'] == []

    def test_skips_malformed_lines_and_searches_trace(self, tmp_path):
        log_file = tmp_path / 'insighttrail.log'
        log_file.write_text(
            'not json\n' + json.dumps(_entry('wanted', '2026-01-01T00:00:00')) + '\n'
        )
        store = FileLogStore(str(log_file))
        assert [item['trace_id'] for item in store.search_by_trace_id('wanted')] == ['wanted']
        assert store.search_by_trace_id('missing') == []

    def test_collects_and_estimates_date_range(self, tmp_path):
        log_file = tmp_path / 'insighttrail.log'
        log_file.write_text('\n'.join([
            json.dumps(_entry('in', '2026-01-02T00:00:00')),
            json.dumps(_entry('out', '2026-02-02T00:00:00')),
        ]) + '\n')
        store = FileLogStore(str(log_file))
        start = datetime.datetime(2026, 1, 1)
        end = datetime.datetime(2026, 1, 31, 23, 59, 59)
        rows = store.collect_for_range(start, end, _parse_datetime, 10)
        assert [row['trace_id'] for row in rows] == ['in']
        assert store.estimate_for_range(start, end, _parse_datetime, 10) == 1


def test_storage_helpers_and_factory(tmp_path):
    entry = {'request': {'path': '/health'}, 'trace_id': 'abc'}
    assert get_source_value(entry, 'request.path') == '/health'
    assert get_source_value(entry, '$') == entry
    assert _coerce_value('3', 'integer') == 3
    assert _coerce_value('true', 'boolean') is True
    assert _parse_datetime('2026-01-01T00:00:00Z').year == 2026
    assert isinstance(create_log_store('file', str(tmp_path / 'x.log')), FileLogStore)
    assert normalize_db_config({'url': 'sqlite:///x.db'})['table'] == 'insighttrail_logs'
