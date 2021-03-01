from datetime import date, datetime, timedelta, timezone
import logging
import uuid
from unittest.mock import Mock

import pytest

from webmon.config import RecorderConfig
from webmon.recorder import init_db, DatabaseRecorder, run_rollup, run_display
from webmon.model import CheckResult


@pytest.fixture
def inited_db(postgresql):
    init_db(postgresql)
    return postgresql


@pytest.fixture
def recorder_config(postgresql):
    return RecorderConfig(
        website_keys=["mywebsite1", "mywebsite2", "mywebsite3"],
        kafka_bootstrap_servers=["stub"],
        database_conn_str=f"host={postgresql.info.host} port={postgresql.info.port} user={postgresql.info.user} dbname={postgresql.info.dbname}",
        kafka_certfile="stub",
        kafka_keyfile="stub",
        kafka_cafile="stub",
    )


def make_check_result(timestamp, url, response_code=200, response_time_ms=200, pattern_matched=True, connect_error=None):
    """
    Create a CheckResult for testing purposes
    """
    return CheckResult(
        check_id=uuid.uuid4(),
        check_time=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        url=url,
        connect_error=connect_error,
        response_code=response_code,
        response_time_ms=response_time_ms,
        pattern_matched=pattern_matched,
    )


def db_query(conn, sql):
    with conn as txn:
        with txn.cursor() as curs:
            curs.execute(sql)
            return curs.fetchall()


def test_recording_rows(inited_db, recorder_config):
    """
    Do a very simple test that 30 results are recorded in the database
    """
    start_time = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    recorder = DatabaseRecorder(recorder_config)
    for website in range(1, 4):
        for i in range(10):
            result = make_check_result(
                start_time + timedelta(minutes=i),
                f"https://mywebsite{website}.com/path?query=val",
            )
            recorder.record_result(f"mywebsite{website}", result)

    assert db_query(inited_db, "SELECT website_key, COUNT(*) FROM check_result_log GROUP BY 1 ORDER BY 1",) == [
        ("mywebsite1", 10),
        ("mywebsite2", 10),
        ("mywebsite3", 10),
    ]

    assert db_query(
        inited_db,
        "SELECT website_key, MIN(check_time), MAX(check_time) FROM check_result_log GROUP BY 1 ORDER BY 1",
    ) == [
        ("mywebsite1", start_time, start_time + timedelta(minutes=9)),
        ("mywebsite2", start_time, start_time + timedelta(minutes=9)),
        ("mywebsite3", start_time, start_time + timedelta(minutes=9)),
    ]

    assert db_query(
        inited_db,
        "SELECT website_key, COUNT(DISTINCT url), MIN(url) FROM check_result_log GROUP BY 1 ORDER BY 1",
    ) == [
        ("mywebsite1", 1, "https://mywebsite1.com/path?query=val"),
        ("mywebsite2", 1, "https://mywebsite2.com/path?query=val"),
        ("mywebsite3", 1, "https://mywebsite3.com/path?query=val"),
    ]


def test_record_error(inited_db, recorder_config):
    check_time = datetime(2020, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
    result = make_check_result(
        check_time,
        "https://bad.website/foo",
        response_code=None,
        response_time_ms=None,
        pattern_matched=None,
        connect_error="fake connect error"
    )
    recorder = DatabaseRecorder(recorder_config)
    recorder.record_result(f"badwebsite", result)
    assert db_query(
        inited_db,
        """
        SELECT
            website_key, check_time, url, connect_error,
            response_code, response_time_ms, pattern_matched
        FROM check_result_log
        """,
    ) == [
        ("badwebsite", check_time, "https://bad.website/foo", "fake connect error", None, None, None),
    ]



def test_duplicate_result(inited_db, recorder_config, caplog):
    """
    Check that the same result, if received twice, is only recorded once,
    and the duplicate receipt is logged
    """
    recorder = DatabaseRecorder(recorder_config)
    result = make_check_result(datetime.now(timezone.utc), "https://example.com/foo")
    with caplog.at_level(logging.INFO):
        recorder.record_result("mysite", result)
        recorder.record_result("mysite", result)

    assert db_query(inited_db, "SELECT website_key, COUNT(*) FROM check_result_log GROUP BY 1 ORDER BY 1",) == [
        ("mysite", 1),
    ]

    assert f"Duplicate result {result.check_id} received" in caplog.text


def log_result_data(recorder_config):
    start_time = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    recorder = DatabaseRecorder(recorder_config)
    for website in range(1, 4):
        for d in range(5):
            for h in range(10):
                result = make_check_result(
                    start_time + timedelta(days=d, hours=h),
                    f"https://mywebsite{website}.com/path?query=val",
                    response_code=100 + (50 * h),
                    response_time_ms=10 + (50 * h),
                    pattern_matched=(h % 2 == 0),
                )
                recorder.record_result(f"mywebsite{website}", result)


def test_rollup_day(inited_db, recorder_config):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = date(2020, 1, 2)
    mock_args.trim = False
    run_rollup(recorder_config, mock_args)

    assert db_query(inited_db, "SELECT * FROM check_daily_summary ORDER BY 1") == [
        ("mywebsite1", date(2020, 1, 2), 10, 2, 2, 2, 2, 2, 0, 10, 235, 460, 5),
        ("mywebsite2", date(2020, 1, 2), 10, 2, 2, 2, 2, 2, 0, 10, 235, 460, 5),
        ("mywebsite3", date(2020, 1, 2), 10, 2, 2, 2, 2, 2, 0, 10, 235, 460, 5),
    ]

    assert db_query(inited_db, "SELECT COUNT(*) FROM check_result_log") == [(150,)]

    mock_args = Mock()
    mock_args.date = date(2020, 1, 4)
    mock_args.trim = True
    run_rollup(recorder_config, mock_args)

    assert db_query(inited_db, "SELECT DATE(check_time), COUNT(*) FROM check_result_log GROUP BY 1 ORDER BY 1") == [
        (date(2020, 1, 1), 30),
        (date(2020, 1, 2), 30),
        (date(2020, 1, 3), 30),
        (date(2020, 1, 5), 30),
    ]


def test_rollup_all(inited_db, recorder_config):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = None
    mock_args.trim = False
    run_rollup(recorder_config, mock_args)

    assert db_query(inited_db, "SELECT * FROM check_daily_summary ORDER BY 1, 2") == [
        (f"mywebsite{n}", date(2020, 1, day), 10, 2, 2, 2, 2, 2, 0, 10, 235, 460, 5)
        for n in range(1, 4)
        for day in range(1, 6)
    ]


def test_rollup_all_with_trim_doesnt_delete(inited_db, recorder_config):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = None
    mock_args.trim = True
    run_rollup(recorder_config, mock_args)

    assert db_query(inited_db, "SELECT COUNT(*) FROM check_result_log") == [(150,)]


def test_display_log_detail(inited_db, recorder_config, capsys):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = None
    mock_args.summary = False
    mock_args.limit = 50
    run_display(recorder_config, mock_args)

    stdout, stderr = capsys.readouterr()
    stdout_lines = stdout.splitlines()

    for column_header in (
        "check_time",
        "website_key",
        "url",
        "connect_error",
        "response_code",
        "response_time_ms",
        "pattern_matched",
    ):
        assert column_header in stdout_lines[1]

    # There should be 50 lines of data and 4 header/footer lines
    assert len(stdout_lines) == 50 + 4


def test_display_log_detail_one_date(inited_db, recorder_config, capsys):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = date(2020, 1, 2)
    mock_args.summary = False
    mock_args.limit = 50
    run_display(recorder_config, mock_args)

    stdout, stderr = capsys.readouterr()
    stdout_lines = stdout.splitlines()

    # There should be 30 lines of data and 4 header/footer lines
    assert len(stdout_lines) == 30 + 4


def test_display_log_summary(inited_db, recorder_config, capsys):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = None
    mock_args.summary = True
    mock_args.limit = 50
    run_display(recorder_config, mock_args)

    stdout, stderr = capsys.readouterr()
    stdout_lines = stdout.splitlines()

    for column_header in (
        "website_key",
        "day",
        "count_all",
        "count_1xx",
        "count_2xx",
        "count_3xx",
        "count_4xx",
        "count_5xx",
        "count_connect_err",
        "min_response_time_ms",
        "avg_response_time_ms",
        "max_response_time_ms",
        "count_pattern_matched",
    ):
        assert column_header in stdout_lines[1]

    # There should be 15 summarised lines of data and 4 header/footer lines
    assert len(stdout_lines) == 15 + 4


def test_display_log_summary_one_date(inited_db, recorder_config, capsys):
    log_result_data(recorder_config)

    mock_args = Mock()
    mock_args.date = date(2020, 1, 2)
    mock_args.summary = True
    mock_args.limit = 50
    run_display(recorder_config, mock_args)

    stdout, stderr = capsys.readouterr()
    stdout_lines = stdout.splitlines()

    # There should be 3 summarised lines of data and 4 header/footer lines
    assert len(stdout_lines) == 3 + 4
