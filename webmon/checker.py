from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import logging
import logging.config
import os
import signal
import time
import urllib.parse
import uuid

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import KafkaError

from . import get_logging_config
from .config import CheckerConfig, topic_for_website_key
from .model import CheckResult


class WebsiteChecker(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__ + ".WebsiteChecker")
        self.to_check = config.sites_to_check
        self.check_interval = config.check_interval
        self.check_timeout = min(1, self.check_interval / 2)
        self.executor = ThreadPoolExecutor(thread_name_prefix="worker-")
        self.bootstrap_servers = config.kafka_bootstrap_servers
        self.kafka_certfile = config.kafka_certfile
        self.kafka_keyfile = config.kafka_keyfile
        self.kafka_cafile = config.kafka_cafile
        self.running = True

    def check_and_report(self, website_key):
        try:
            self.report_result(website_key, self.check_site(website_key))
        except Exception as exc:
            logger.exception("Unhandled exception checking %s: %s", website_key, exc)

    def check_site(self, website_key) -> CheckResult:
        """
        Runs a check for a single site. If the connection or request causes an exception,
        it'll be converted to a CheckResult with connect_error describing the exception,
        rather than being raised out of this method.
        """
        url = self.to_check[website_key].url
        check_time_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        self.logger.debug("Checking key %s (url %s)", website_key, url)
        try:
            return self.do_request(website_key, url, check_time_str)
        except Exception as exc:
            # It's expected that sometimes there will be connect errors, so we only log at DEBUG level to avoid noise:
            self.logger.debug("Exception checking %s (url %s)", website_key, url, exc_info=True)
            return CheckResult(
                check_id=str(uuid.uuid4()),
                check_time=check_time_str,
                url=url,
                connect_error=str(exc),
                response_code=None,
                response_time_ms=None,
                pattern_matched=None,
            )

    def do_request(self, website_key, url, check_time_str):
        """
        Do the work of connecting and checking a website. This method is allowed to raise an exception
        on connection errors, to be caught and reported.
        """
        split = urllib.parse.urlsplit(url)
        if split.scheme == "http":
            client = http.client.HTTPConnection(split.netloc, timeout=self.check_timeout)
        elif split.scheme == "https":
            client = http.client.HTTPSConnection(split.netloc, timeout=self.check_timeout)

        # Assuming we don't want to measure TCP connection time but HTTP response time, we connect first:
        client.connect()

        req_line = split.path
        if not req_line.startswith("/"):
            req_line = "/" + req_line
        if split.query:
            req_line += f"?{split.query}"

        req_start_time = time.perf_counter()
        client.request("GET", req_line)
        # If we didn't want to count the time spent sending the request, we could start measuring time here
        resp = client.getresponse()
        req_end_time = time.perf_counter()
        elapsed = req_end_time - req_start_time

        self.logger.debug("Check for %s returned %d in %f secs", website_key, resp.status, elapsed)

        if self.to_check[website_key].pattern:
            resp_body = resp.read()
            try:
                encoding = resp.msg.get_content_charset("utf-8")
                pattern_matched = self.to_check[website_key].pattern.search(resp_body.decode(encoding)) is not None
            except Exception as exc:
                self.logger.warn(
                    "Unexpected exception checking pattern on %s (url %s)",
                    website_key,
                    url,
                    exc_info=True,
                )
                pattern_matched = False
        else:
            pattern_matched = None

        return CheckResult(
            check_id=str(uuid.uuid4()),
            check_time=check_time_str,
            url=url,
            connect_error=None,
            response_code=resp.status,
            response_time_ms=int(elapsed * 1000.0),
            pattern_matched=pattern_matched,
        )

    def report_result(self, website_key, result):
        self.logger.debug("Sending %s result %s to Kafka", website_key, result)
        try:
            future = self.producer.send(
                topic_for_website_key(website_key), key=website_key.encode("utf-8"), value=result
            )
            record_metadata = future.get(timeout=10)
            self.logger.debug("Successfully sent result to Kafka topic: %s", record_metadata)
        except Exception as exc:
            self.logger.error("Unexpected error sending result to Kafka: %s", exc, exc_info=exc)

    def common_kafka_args(self):
        return dict(
            bootstrap_servers=self.bootstrap_servers,
            client_id="webmon-checker",
            security_protocol="SSL",
            ssl_certfile=self.kafka_certfile,
            ssl_keyfile=self.kafka_keyfile,
            ssl_cafile=self.kafka_cafile,
        )

    def create_topics(self):
        """
        For each website key, if any Kafka topic is missing, create it
        """
        consumer = KafkaConsumer(group_id="webmon-checker", **self.common_kafka_args())
        existing_topics = consumer.topics()
        new_topics = []
        for key in self.to_check.keys():
            if topic_for_website_key(key) not in existing_topics:
                new_topics.append(topic_for_website_key(key))

        if new_topics:
            admin_client = KafkaAdminClient(**self.common_kafka_args())
            self.logger.info("Creating topics: %s", ",".join(new_topics))
            admin_client.create_topics(
                [
                    NewTopic(name=new_topic_name, num_partitions=1, replication_factor=1)
                    for new_topic_name in new_topics
                ],
                timeout_ms=30_000,
            )

    def run_checker(self):
        self.create_topics()
        self.producer = KafkaProducer(
            value_serializer=lambda m: json.dumps(m.asdict()).encode("utf-8"), retries=3, **self.common_kafka_args()
        )
        while self.running:
            self.last_check = time.monotonic()
            self.executor.map(self.check_and_report, self.to_check.keys())
            time_to_sleep = (self.last_check + self.check_interval) - time.monotonic()
            if self.running and time_to_sleep > 0:
                time.sleep(time_to_sleep)

    def stop(self):
        self.running = False
        self.logger.info("Shutting down checker...")


def run_checker_app():
    logging.config.dictConfig(get_logging_config(os.environ.get("WBM_LOGLEVEL", "INFO")))
    config = CheckerConfig.from_environment()
    checker = WebsiteChecker(config)

    def shutdown(signum, frame):
        checker.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    checker.run_checker()
