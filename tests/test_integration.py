import os
import threading
import time

from kafka.admin import KafkaAdminClient
import psycopg2
import pytest

from webmon.checker import WebsiteChecker
from webmon.config import CheckerConfig, RecorderConfig, topic_for_website_key
from webmon.recorder import DatabaseRecorder, init_db

inttest = pytest.mark.skipif(
    "not config.getvalue('inttests')", reason="Integration tests must be explicitly enabled with --inttests"
)


@pytest.fixture
def external_postgres():
    conn = psycopg2.connect(os.environ["WBM_DB_CONN_STR"])
    init_db(conn)
    yield conn

    # Clean up after test
    with conn as txn:
        with txn.cursor() as curs:
            curs.execute("DROP TABLE check_result_log")
            curs.execute("DROP TABLE check_daily_summary")


@pytest.fixture
def patched_env(httpserver, monkeypatch):
    """
    Injects environment variables to set website URLs to check
    """
    monkeypatch.setenv("WBM_WEBSITE_KEYS", "test_foo,test_bar,bare_host_url,test_bad,test_pat,test_404,test_500")
    monkeypatch.setenv("WBM_WEBSITE_TEST_FOO_URL", httpserver.url_for("/foo") + "?bar=baz")
    monkeypatch.setenv("WBM_WEBSITE_TEST_BAR_URL", httpserver.url_for("/bar"))
    monkeypatch.setenv("WBM_WEBSITE_BARE_HOST_URL_URL", httpserver.url_for("/").rstrip("/"))
    monkeypatch.setenv("WBM_WEBSITE_TEST_BAD_URL", "https://localhost:250/bad")
    monkeypatch.setenv("WBM_WEBSITE_TEST_PAT_URL", httpserver.url_for("/pat"))
    monkeypatch.setenv("WBM_WEBSITE_TEST_PAT_PATTERN", "I (have|contain) some text")
    monkeypatch.setenv("WBM_WEBSITE_TEST_404_URL", httpserver.url_for("/four-oh-four"))
    monkeypatch.setenv("WBM_WEBSITE_TEST_500_URL", httpserver.url_for("/five-hundred"))
    monkeypatch.setenv("WBM_CHECK_INTERVAL", "5")


@pytest.fixture
def default_httpserver(httpserver):
    httpserver.expect_request("/foo", query_string="bar=baz", method="GET").respond_with_data(
        "Hello world for /foo!", content_type="text/plain"
    )
    httpserver.expect_request("/bar", method="GET").respond_with_data(
        "Hello world for /bar!", content_type="text/plain"
    )
    httpserver.expect_request("/", method="GET").respond_with_data("Hello world for /!", content_type="text/plain")
    httpserver.expect_request("/pat", method="GET").respond_with_data(
        "Hello, I have some text", content_type="text/plain"
    )
    httpserver.expect_request("/four-oh-four", method="GET").respond_with_data(
        "Page not found", status=404, content_type="text/plain"
    )
    httpserver.expect_request("/five-hundred", method="GET").respond_with_data(
        "Internal error", status=500, content_type="text/plain"
    )
    return httpserver


@pytest.fixture
def running_components(default_httpserver, external_postgres, patched_env):
    checker_config = CheckerConfig.from_environment()
    checker = WebsiteChecker(checker_config)

    recorder = DatabaseRecorder(RecorderConfig.from_environment())

    checker.create_topics()

    recorder_thread = threading.Thread(target=recorder.run_consumer)
    recorder_thread.start()

    checker_thread = threading.Thread(target=checker.run_checker)
    checker_thread.start()

    yield (checker, recorder)

    checker.stop()
    recorder.stop()
    checker_thread.join(timeout=10)
    recorder_thread.join(timeout=10)

    # Clean up Kafka topics
    admin_client = KafkaAdminClient(**checker.common_kafka_args())
    admin_client.delete_topics([topic_for_website_key(key) for key in checker_config.sites_to_check.keys()])
    admin_client.delete_consumer_groups(["webmon-recorder"])

    if checker_thread.is_alive() or recorder_thread.is_alive():
        raise RuntimeError("Timed out waiting for threads to finish")


@inttest
def test_all_responses(external_postgres, running_components):
    # Poll the database for expected stored results
    for _retry in range(20):
        with external_postgres as txn:
            with txn.cursor() as curs:
                curs.execute("SELECT COUNT(*) FROM check_result_log")
                count = curs.fetchone()[0]
                # Expect one result for each website
                if count == 7:
                    curs.execute(
                        """
                        SELECT
                            website_key, url, connect_error, response_code,
                            response_time_ms, pattern_matched
                        FROM check_result_log
                        """
                    )
                    results = curs.fetchall()
                    break
                else:
                    time.sleep(1)
    else:
        results = []

    results_by_key = {row[0]: row[1:] for row in results}

    assert results_by_key["test_foo"][0].endswith("/foo?bar=baz")
    assert results_by_key["test_foo"][1:3] == (None, 200)
    assert results_by_key["test_foo"][3] > 0
    assert results_by_key["test_foo"][4] is None

    assert results_by_key["test_bar"][0].endswith("/bar")
    assert results_by_key["test_bar"][1:3] == (None, 200)
    assert results_by_key["test_bar"][3] > 0
    assert results_by_key["test_bar"][4] is None

    assert not results_by_key["bare_host_url"][0].endswith("/")
    assert results_by_key["bare_host_url"][1:3] == (None, 200)
    assert results_by_key["bare_host_url"][3] > 0
    assert results_by_key["bare_host_url"][4] is None

    # The "bad" URL should result in a connection error
    assert results_by_key["test_bad"][0].endswith("/bad")
    assert "Errno" in results_by_key["test_bad"][1]
    assert results_by_key["test_bad"][3:5] == (None, None)

    assert results_by_key["test_pat"][0].endswith("/pat")
    assert results_by_key["test_pat"][1:3] == (None, 200)
    assert results_by_key["test_pat"][3] > 0
    assert results_by_key["test_pat"][4] == True

    assert results_by_key["test_404"][0].endswith("/four-oh-four")
    assert results_by_key["test_404"][1:3] == (None, 404)
    assert results_by_key["test_404"][3] > 0
    assert results_by_key["test_404"][4] is None

    assert results_by_key["test_500"][0].endswith("/five-hundred")
    assert results_by_key["test_500"][1:3] == (None, 500)
    assert results_by_key["test_500"][3] > 0
    assert results_by_key["test_500"][4] is None
