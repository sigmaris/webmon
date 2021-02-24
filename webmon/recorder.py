import json
import re

import iso8601
from kafka import KafkaConsumer
from psycopg2.pool import SimpleConnectionPool
import psycopg2.extras

from .config import RecorderConfig
from .model import CheckResult


DB_CREATE_STMTS = [
    """
    CREATE TABLE check_result_log (
        check_id UUID PRIMARY KEY,
        website_key VARCHAR(50),
        check_time TIMESTAMPTZ,
        -- There's no limit in HTTP on URL length, but there is a de-facto limit of 2083 characters
        -- which is the maximum supported by IE8 and 9. So we could optionally agree a limit for
        -- our system and use VARCHAR(2083) here instead of TEXT:
        url TEXT,
        response_code INTEGER,
        response_time_ms INTEGER,
        pattern_matched BOOLEAN
    )
    """,
]


def init_db(db_conn):
    with db_conn as txn:
        with txn.cursor() as curs:
            for stmt in DB_CREATE_STMTS:
                curs.execute(stmt)


class DatabaseRecorder(object):
    def __init__(self, config):
        self.website_keys = config.website_keys
        self.bootstrap_servers = config.kafka_bootstrap_servers
        self.db_pool = SimpleConnectionPool(0, 5, config.database_conn_str)
        psycopg2.extras.register_uuid()
        # TODO: shutdown queue

    def run_consumer(self):
        """
        This method runs the Kafka consumer and writes results into the database until a shutdown signal
        is received.
        """
        topic_pattern = re.compile(r"webmon\.[^.]+\.checkresult")
        topics = ["webmon.{key}.checkresult" for key in self.website_keys]
        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            client_id="webmon-recorder",
            group_id="webmon-recorder",
            value_deserializer=lambda m: CheckResult(**json.loads(m.decode("utf-8"))),
            # Make sure we unblock this thread to check for shutdown at least every 2s
            consumer_timeout_ms=2000
        )
        running = True
        while running:
            for message in consumer:
                print(message)
    
    def record_result(self, website_key, result):
        """
        Write a single wire-format result into the database
        """
        # Convert the wire-format result into a database record
        row_to_write = result.asdict()
        row_to_write["website_key"] = website_key
        # The wire format for check_time is an ISO8601 timestamp string, parse this:
        row_to_write["check_time"] = iso8601.parse_date(row_to_write["check_time"])

        try:
            db_conn = self.db_pool.getconn()
            with db_conn as txn:
                with txn.cursor() as curs:
                    curs.execute(
                        """
                        INSERT INTO check_result_log(
                            check_id, website_key, check_time, url,
                            response_code, response_time_ms, pattern_matched
                        ) VALUES (
                            %(check_id)s, %(website_key)s, %(check_time)s, %(url)s,
                            %(response_code)s, %(response_time_ms)s, %(pattern_matched)s
                        )
                        """,
                        row_to_write,
                    )
        finally:
            self.db_pool.putconn(db_conn)



def run_recorder_app():
    config = RecorderConfig.from_environment()
    recorder = DatabaseRecorder(config)
    recorder.run_consumer()
