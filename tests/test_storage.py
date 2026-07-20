import json

from insighttrail.storage import FileLogStore


def test_file_log_store_retains_more_than_5000_entries_by_default(tmp_path):
    log_file = tmp_path / "insighttrail.log"
    with log_file.open("w", encoding="utf-8") as handle:
        for index in range(6000):
            handle.write(json.dumps({"message": f"request-{index}"}) + "\n")

    store = FileLogStore(str(log_file))

    assert len(store.all_cached()) == 6000
    page = store.get_page(limit=6000)
    assert len(page["logs"]) == 6000
    assert page["logs"][0]["message"] == "request-0"
    assert page["logs"][-1]["message"] == "request-5999"


def test_file_log_store_reports_has_more_for_cursor_pages(tmp_path):
    log_file = tmp_path / "insighttrail.log"
    with log_file.open("w", encoding="utf-8") as handle:
        for index in range(10):
            handle.write(json.dumps({"message": f"request-{index}"}) + "\n")

    store = FileLogStore(str(log_file))
    page = store.get_page(limit=3, cursor=0)

    assert len(page["logs"]) == 3
    assert page["cursor"] == 3
    assert page["has_more"] is True
