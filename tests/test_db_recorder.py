from datetime import datetime, timedelta, timezone
import uuid

import pytest

from webmon.config import RecorderConfig
from webmon.recorder import init_db, DatabaseRecorder
from webmon.model import CheckResult


@pytest.fixture
def inited_db(postgresql):
    init_db(postgresql)
    return postgresql


@pytest.fixture
def recorder_config(postgresql):
    return RecorderConfig(
        website_keys=["mywebsite1", "mywebsite2", "mywebsite3"],
        kafka_bootstrap_servers=["localhost"],
        database_conn_str=f"host={postgresql.info.host} port={postgresql.info.port} user={postgresql.info.user} dbname={postgresql.info.dbname}"
    ) 


def make_check_result(timestamp, url, response_code=200, response_time_ms=200, pattern_matched=True):
    """
    Create a CheckResult for testing purposes
    """
    return CheckResult(
        check_id=uuid.uuid4(),
        check_time=timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        url=url,
        response_code=response_code,
        response_time_ms=response_time_ms,
        pattern_matched=pattern_matched
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
                f"https://mywebsite{website}.com/path?query=val"
            )
            recorder.record_result(f"mywebsite{website}", result)

    assert db_query(inited_db, "SELECT website_key, COUNT(*) FROM check_result_log GROUP BY 1 ORDER BY 1") == [
        ("mywebsite1", 10),
        ("mywebsite2", 10),
        ("mywebsite3", 10),
    ]

    assert db_query(inited_db, "SELECT website_key, MIN(check_time), MAX(check_time) FROM check_result_log GROUP BY 1 ORDER BY 1") == [
        ("mywebsite1", start_time, start_time + timedelta(minutes=9)),
        ("mywebsite2", start_time, start_time + timedelta(minutes=9)),
        ("mywebsite3", start_time, start_time + timedelta(minutes=9)),
    ]

