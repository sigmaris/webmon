import os
from typing import List, NamedTuple


class ConfigurationError(Exception):
    """
    This exception indicates the app has been configured wrongly or a problem
    has been detected in parsing configuration.
    """


class RecorderConfig(NamedTuple):
    """
    Wraps the configuration for the database recorder
    """
    # Which website keys should this recorder listen for checks for?
    website_keys: List[str]
    # List of Kafka bootstrap servers
    kafka_bootstrap_servers: List[str]
    # Connection string for the PostgreSQL database to write results into
    database_conn_str: str

    @classmethod
    def from_environment(cls):
        website_keys = os.environ.get("WBM_WEBSITE_KEYS", "*").split(",")

        try:
            kafka_bootstrap_servers = os.environ["WBM_KAFKA_BOOT_SERVERS"].split(",")
        except Exception as exc:
            raise ConfigurationError(
                "Kafka bootstrap server(s) should be provided as a comma-separated list in env var WBM_KAFKA_BS_SERVERS"
            ) from exc

        try:
            database_conn_str = os.environ["WBM_DB_CONN_STR"]
        except Exception as exc:
            raise ConfigurationError(
                "PostgreSQL database connection string should be provided in env var WBM_DB_CONN_STR"
            ) from exc

        return cls(
            website_keys=website_keys,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            database_conn_str=database_conn_str,
        )
