import json

from insighttrail.storage import FileLogStore


def test_file_log_store_cursor_reports_more_results(tmp_path):
    log_file = tmp_path / 'events.jsonl'
    entries = [{'request': {'path': f'/reports/{index}'}} for index in range(4)]
    log_file.write_text(
        '\n'.join(json.dumps(entry) for entry in entries),
        encoding='utf-8',
    )
    store = FileLogStore(str(log_file))

    page = store.get_page(limit=2, cursor=1)

    assert [log['_id'] for log in page['logs']] == [2, 3]
    assert page['cursor'] == 3
    assert page['has_more'] is True
