"""
webmon database recorder component: this listens for results from the website checker component
and records them in a PostgreSQL database. It also contains utilities to create the database
tables, to roll-up check results into a daily summary and to trim older results from the result
log.
"""
import argparse
from datetime import datetime
import json
import logging
import os
import re

import iso8601
from kafka import KafkaConsumer
from psycopg2.pool import SimpleConnectionPool
import psycopg2.extras
from tabulate import tabulate

from .config import RecorderConfig, topic_for_website_key, website_key_for_topic
from .model import CheckResult


DB_CREATE_STMTS = (
    """
    CREATE TABLE check_result_log (
        check_id UUID NOT NULL PRIMARY KEY,
        website_key VARCHAR(50) NOT NULL,
        check_time TIMESTAMPTZ NOT NULL,
        -- There's no limit in HTTP on URL length, but there is a de-facto limit of 2083 characters
        -- which is the maximum supported by IE8 and 9. So we could optionally agree a limit for
        -- our system and use VARCHAR(2083) here instead of TEXT:
        url TEXT NOT NULL,
        connect_error TEXT,
        response_code INTEGER,
        response_time_ms INTEGER,
        pattern_matched BOOLEAN
    )
    """,
    """
    CREATE TABLE check_daily_summary (
        website_key VARCHAR(50) NOT NULL,
        day DATE NOT NULL,
        count_all INTEGER NOT NULL,
        count_1xx INTEGER NOT NULL,
        count_2xx INTEGER NOT NULL,
        count_3xx INTEGER NOT NULL,
        count_4xx INTEGER NOT NULL,
        count_5xx INTEGER NOT NULL,
        count_connect_err INTEGER NOT NULL,
        min_response_time_ms INTEGER,
        avg_response_time_ms INTEGER,
        max_response_time_ms INTEGER,
        count_pattern_matched INTEGER NOT NULL,
        PRIMARY KEY(website_key, day)
    )
    """,
)

SUMMARY_SELECT_SQL = """
SELECT
    website_key,
    DATE(check_time) AS day,
    COUNT(*) AS count_all,
    SUM(CASE WHEN response_code BETWEEN 100 AND 199 THEN 1 ELSE 0 END) AS count_1xx,
    SUM(CASE WHEN response_code BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS count_2xx,
    SUM(CASE WHEN response_code BETWEEN 300 AND 399 THEN 1 ELSE 0 END) AS count_3xx,
    SUM(CASE WHEN response_code BETWEEN 400 AND 499 THEN 1 ELSE 0 END) AS count_4xx,
    SUM(CASE WHEN response_code BETWEEN 500 AND 599 THEN 1 ELSE 0 END) AS count_5xx,
    SUM(CASE WHEN connect_error IS NOT NULL THEN 1 ELSE 0 END) AS count_connect_err,
    MIN(response_time_ms) AS min_response_time_ms,
    AVG(response_time_ms) AS avg_response_time_ms,
    MAX(response_time_ms) AS max_response_time_ms,
    SUM(CASE WHEN pattern_matched THEN 1 ELSE 0 END) AS count_pattern_matched
FROM check_result_log
{optional_where}
GROUP BY 1, 2
"""
SUMMARY_INSERT_SQL = """
INSERT INTO check_daily_summary (
    website_key,
    day,
    count_all,
    count_1xx,
    count_2xx,
    count_3xx,
    count_4xx,
    count_5xx,
    count_connect_err,
    min_response_time_ms,
    avg_response_time_ms,
    max_response_time_ms,
    count_pattern_matched
)
{select}
ON CONFLICT (website_key, day) DO UPDATE SET
    count_all = EXCLUDED.count_all,
    count_1xx = EXCLUDED.count_1xx,
    count_2xx = EXCLUDED.count_2xx,
    count_3xx = EXCLUDED.count_3xx,
    count_4xx = EXCLUDED.count_4xx,
    count_5xx = EXCLUDED.count_5xx,
    count_connect_err = EXCLUDED.count_connect_err,
    min_response_time_ms = EXCLUDED.min_response_time_ms,
    avg_response_time_ms = EXCLUDED.avg_response_time_ms,
    max_response_time_ms = EXCLUDED.max_response_time_ms,
    count_pattern_matched = EXCLUDED.count_pattern_matched
"""


def init_db(db_conn):
    """
    This approach just initializes the database with hardcoded SQL CREATE statements;
    in a larger project with more time to develop, I would use a DB migration tool like
    alembic or yoyo.
    """
    with db_conn as txn:
        with txn.cursor() as curs:
            for stmt in DB_CREATE_STMTS:
                curs.execute(stmt)


class DatabaseRecorder(object):
    def __init__(self, config):
        self.logger = logging.getLogger(__name__ + ".DatabaseRecorder")
        self.website_keys = config.website_keys
        self.bootstrap_servers = config.kafka_bootstrap_servers
        self.kafka_certfile = config.kafka_certfile
        self.kafka_keyfile = config.kafka_keyfile
        self.kafka_cafile = config.kafka_cafile

        self.db_pool = SimpleConnectionPool(0, 5, config.database_conn_str)
        psycopg2.extras.register_uuid()
        self.running = True

    def run_consumer(self):
        """
        This method runs the Kafka consumer and writes results into the database until a shutdown signal
        is received.
        """
        topics = [topic_for_website_key(key) for key in self.website_keys]
        self.logger.debug("Consuming on topics: %s", ", ".join(topics))
        consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            client_id="webmon-recorder",
            group_id="webmon-recorder",
            value_deserializer=lambda m: CheckResult(**json.loads(m.decode("utf-8"))),
            # Make sure we unblock this thread to check for shutdown at least every 2s
            consumer_timeout_ms=2000,
            security_protocol="SSL",
            ssl_certfile=self.kafka_certfile,
            ssl_keyfile=self.kafka_keyfile,
            ssl_cafile=self.kafka_cafile,
        )
        while self.running:
            self.logger.debug("Running Kafka consumer")
            for message in consumer:
                self.logger.debug("Received %s on topic %s", message.value, message.topic)
                self.record_result(website_key_for_topic(message.topic), message.value)
                if not self.running:
                    break

    def stop(self):
        self.running = False

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
                            check_id, website_key, check_time, url, connect_error,
                            response_code, response_time_ms, pattern_matched
                        ) VALUES (
                            %(check_id)s, %(website_key)s, %(check_time)s, %(url)s, %(connect_error)s,
                            %(response_code)s, %(response_time_ms)s, %(pattern_matched)s
                        )
                        """,
                        row_to_write,
                    )
        except psycopg2.errors.UniqueViolation:
            self.logger.info("Duplicate result %s received, discarding it", result.check_id, extra={"result": result})
        finally:
            self.db_pool.putconn(db_conn)


def tabulate_result(cursor):
    headers = [column[0] for column in cursor.description]  # get name
    table = cursor.fetchall()
    return tabulate(table, headers=headers, tablefmt="psql")


def setup_logging():
    # TODO: maybe lower log level for Kafka?
    logging.basicConfig(level=os.environ.get("WBM_LOGLEVEL", "INFO"))


def run_record(config, args):
    recorder = DatabaseRecorder(config)
    recorder.run_consumer()


def run_initdb(config, args):
    db_conn = psycopg2.connect(config.database_conn_str)
    init_db(db_conn)
    logging.info("Initialised database.")
    db_conn.close()


def run_rollup(config, args):
    if args.date is not None:
        date_where = "WHERE DATE(check_time) = %(day)s"
        params = dict(day=args.date)
    else:
        date_where = ""
        params = {}
    with psycopg2.connect(config.database_conn_str) as txn:
        with txn.cursor() as curs:
            summary_select = SUMMARY_SELECT_SQL.format(optional_where=date_where)
            insert = SUMMARY_INSERT_SQL.format(select=summary_select)
            curs.execute(insert, params)
            if args.trim:
                if args.date is not None:
                    curs.execute(f"DELETE FROM check_result_log {date_where}", params)
                else:
                    print("Trimming requires a single date to trim - will not delete all data")


def run_display(config, args):
    with psycopg2.connect(config.database_conn_str) as txn:
        with txn.cursor() as curs:
            optional_where = ""
            params = dict(limit=args.limit)
            if args.summary:
                if args.date is not None:
                    optional_where = "WHERE day = %(day)s"
                    params["day"] = args.date
                # First look for rolled up data
                curs.execute(
                    f"""
                SELECT
                    website_key, day, count_all, count_1xx, count_2xx, count_3xx, count_4xx, count_5xx,
                    count_connect_err,
                    min_response_time_ms, avg_response_time_ms, max_response_time_ms,
                    count_pattern_matched
                FROM check_daily_summary
                {optional_where}
                """,
                    params,
                )
                if curs.rowcount == 0:
                    if args.date is not None:
                        optional_where = "WHERE DATE(check_time) = %(day)s"
                    curs.execute(SUMMARY_SELECT_SQL.format(optional_where=optional_where), params)
            else:
                if args.date is not None:
                    optional_where = "WHERE DATE(check_time) = %(day)s"
                    params["day"] = args.date
                curs.execute(
                    f"""
                SELECT
                    check_time, website_key, url, connect_error,
                    response_code, response_time_ms, pattern_matched
                FROM check_result_log
                {optional_where}
                ORDER BY check_time DESC
                LIMIT %(limit)s
                """,
                    params,
                )
            print(tabulate_result(curs))


def run_recorder_app():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers()
    subcommands.add_parser("record").set_defaults(func=run_record)
    subcommands.add_parser("initdb").set_defaults(func=run_initdb)
    rollup_parser = subcommands.add_parser("rollup")
    rollup_parser.set_defaults(func=run_rollup)
    rollup_parser.add_argument("--trim", action="store_true", help="DELETE data from log after storing rollup")
    display_parser = subcommands.add_parser("display")
    display_parser.set_defaults(func=run_display)
    display_parser.add_argument("--summary", action="store_true", help="Display summary instead of list of results")
    display_parser.add_argument("--limit", type=int, default=50, help="Display this many results")
    for p in (rollup_parser, display_parser):
        p.add_argument("--date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(), help="Date to operate on")
    args = parser.parse_args()
    setup_logging()
    config = RecorderConfig.from_environment()
    func = getattr(args, "func", run_record)
    func(config, args)
