from datetime import datetime, timezone
import re
import time

import iso8601
import pytest
from werkzeug import Response

from webmon.checker import WebsiteChecker
from webmon.model import CheckResult
from webmon.config import CheckerConfig, SiteConfig

UUID_PATTERN = re.compile(r"(?i)^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


def checker_config(httpserver, pattern=None):
    return CheckerConfig(
        sites_to_check={
            "test_foo": SiteConfig(
                url=httpserver.url_for("/foo") + "?bar=baz",
                pattern=pattern,
            ),
            "test_bar": SiteConfig(
                url=httpserver.url_for("/bar"),
                pattern=pattern,
            ),
            "bare_host_url": SiteConfig(url=httpserver.url_for("/").rstrip("/"), pattern=pattern),
        },
        check_interval=60,
        kafka_bootstrap_servers=["stub"],
        kafka_certfile="stub",
        kafka_keyfile="stub",
        kafka_cafile="stub",
    )


def assert_result_valid(result: CheckResult):
    """
    Checks some expected invariants on a given CheckResult
    """
    assert UUID_PATTERN.match(result.check_id) is not None
    assert isinstance(iso8601.parse_date(result.check_time), datetime)
    assert isinstance(result.url, str)
    if result.connect_error is not None:
        assert isinstance(result.connect_error, str)
        assert len(result.connect_error) > 0
    else:
        assert 100 <= result.response_code <= 599
        assert result.response_time_ms >= 0
        assert result.pattern_matched in (True, False, None)


@pytest.mark.parametrize(
    "key,url,query_string",
    [
        ("test_bar", "/bar", None),
        ("test_foo", "/foo", "bar=baz"),
        ("bare_host_url", "/", None),
    ],
)
def test_ok_responses(httpserver, key, url, query_string):
    httpserver.expect_request(url, query_string=query_string, method="GET").respond_with_data(
        "Hello world!", content_type="text/plain"
    )

    checker = WebsiteChecker(checker_config(httpserver, pattern=None))

    start = datetime.now(timezone.utc).replace(microsecond=0)
    result = checker.check_site(key)
    end = datetime.now(timezone.utc)

    assert_result_valid(result)
    assert start <= iso8601.parse_date(result.check_time) <= end
    assert result.response_code == 200


@pytest.mark.parametrize(
    "status",
    [
        (400),
        (404),
        (500),
        (503),
    ],
)
def test_error_responses(httpserver, status):
    httpserver.expect_request("/bar", method="GET").respond_with_data(
        "There has been an error!", status=status, content_type="text/plain"
    )

    checker = WebsiteChecker(checker_config(httpserver, pattern=None))

    result = checker.check_site("test_bar")

    assert_result_valid(result)
    assert result.response_code == status


def test_connect_error():
    no_webserver_config = CheckerConfig(
        sites_to_check={
            "test_bad": SiteConfig(
                # Port 250 is reserved, hopefully nothing will be listening on it
                url="https://localhost:250/bad",
                pattern=None,
            ),
        },
        check_interval=5,
        kafka_bootstrap_servers=["stub"],
        kafka_certfile="stub",
        kafka_keyfile="stub",
        kafka_cafile="stub",
    )
    checker = WebsiteChecker(no_webserver_config)
    result = checker.check_site("test_bad")

    assert_result_valid(result)

    assert "Errno" in result.connect_error


@pytest.mark.parametrize(
    "pattern,response,expected",
    [
        (re.compile(r"world"), "Hello, World!", False),
        (re.compile(r"(?i)world"), "Hello, World!", True),
        (re.compile(r"a{5}"), "five a's aaaaa", True),
        (None, "Hello again", None),
    ],
)
def test_pattern_matching(httpserver, pattern, response, expected):
    httpserver.expect_request("/foo", query_string="bar=baz", method="GET").respond_with_data(
        response, content_type="text/plain"
    )

    checker = WebsiteChecker(checker_config(httpserver, pattern=pattern))

    result = checker.check_site("test_foo")

    assert_result_valid(result)
    assert result.pattern_matched == expected


@pytest.mark.parametrize(
    "status,delay_ms",
    [
        (200, 100),
        (200, 200),
        (400, 100),
        (400, 300),
        (500, 1),
    ],
)
def test_response_times(httpserver, status, delay_ms):
    def handler(request):
        time.sleep(delay_ms / 1000)
        return Response("Hello, World!", status=status)

    httpserver.expect_request("/foo", query_string="bar=baz", method="GET").respond_with_handler(handler)

    checker = WebsiteChecker(checker_config(httpserver, pattern=None))

    result = checker.check_site("test_foo")

    assert_result_valid(result)
    assert result.response_code == status
    assert result.response_time_ms >= delay_ms
