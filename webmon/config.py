import os
import re
from typing import List, NamedTuple, Dict, Pattern
import urllib.parse


class ConfigurationError(Exception):
    """
    This exception indicates the app has been configured wrongly or a problem
    has been detected in parsing configuration.
    """


def kafka_config_from_env():
    """
    Read Kafka config values from environment vars, common to checker and recorder config.
    """
    try:
        kafka_bootstrap_servers = os.environ["WBM_KAFKA_BOOT_SERVERS"].split(",")
    except Exception as exc:
        raise ConfigurationError(
            "Kafka bootstrap server(s) should be provided as a comma-separated list in env var WBM_KAFKA_BOOT_SERVERS"
        ) from exc

    try:
        kakfa_certfile = os.environ["WBM_KAFKA_CERTFILE"]
        kakfa_keyfile = os.environ["WBM_KAFKA_KEYFILE"]
        kakfa_cafile = os.environ["WBM_KAFKA_CAFILE"]
    except Exception as exc:
        raise ConfigurationError(
            "Kafka SSL client cert, key and CA file paths should be provided in env vars WBM_KAFKA_CERTFILE, WBM_KAFKA_KEYFILE and WBM_KAFKA_CAFILE"
        ) from exc

    return (kafka_bootstrap_servers, kakfa_certfile, kakfa_keyfile, kakfa_cafile)


def topic_for_website_key(key):
    return f"webmon.{key}.checkresult"


def website_key_for_topic(topic):
    return re.fullmatch(r"webmon\.([^.]+)\.checkresult", topic).group(1)


class RecorderConfig(NamedTuple):
    """
    Wraps the configuration for the database recorder component
    """

    # Which website keys should this recorder listen for checks for?
    website_keys: List[str]
    # List of Kafka bootstrap servers
    kafka_bootstrap_servers: List[str]
    # Connection string for the PostgreSQL database to write results into
    database_conn_str: str
    # Kafka Client certificate details
    kafka_cafile: str
    kafka_certfile: str
    kafka_keyfile: str

    @classmethod
    def from_environment(cls):
        website_keys = os.environ.get("WBM_WEBSITE_KEYS", "*").split(",")

        for key in website_keys:
            if re.match(r"^[\w_-]+$", key) is None:
                raise ConfigurationError("Each website key must consist of alphanumeric -, and _ characters only.")

        try:
            database_conn_str = os.environ["WBM_DB_CONN_STR"]
        except Exception as exc:
            raise ConfigurationError(
                "PostgreSQL database connection string should be provided in env var WBM_DB_CONN_STR"
            ) from exc

        (
            kafka_bootstrap_servers,
            kakfa_certfile,
            kakfa_keyfile,
            kakfa_cafile,
        ) = kafka_config_from_env()

        return cls(
            website_keys=website_keys,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            database_conn_str=database_conn_str,
            kafka_certfile=kakfa_certfile,
            kafka_keyfile=kakfa_keyfile,
            kafka_cafile=kakfa_cafile,
        )


class SiteConfig(NamedTuple):
    url: str
    pattern: Pattern


class CheckerConfig(NamedTuple):
    """
    Wraps the configuration for the website checker component
    """

    # Dictionary of website key -> url config of sites to check
    sites_to_check: Dict[str, SiteConfig]
    # Check interval in seconds
    check_interval: int
    # List of Kafka bootstrap servers
    kafka_bootstrap_servers: List[str]
    # Kafka Client certificate details
    kafka_cafile: str
    kafka_certfile: str
    kafka_keyfile: str

    @classmethod
    def from_environment(cls):
        try:
            website_key_names = os.environ["WBM_WEBSITE_KEYS"].split(",")
        except Exception as exc:
            raise ConfigurationError(
                "Keys of websites to check should be provided as a comma-separated list in env var WBM_WEBSITE_KEYS"
            ) from exc

        for key in website_key_names:
            if re.match(r"^[\w_-]+$", key) is None:
                raise ConfigurationError("Each website key must consist of alphanumeric -, and _ characters only.")

        try:
            sites_to_check = {
                key: dict(
                    url=os.environ[f"WBM_WEBSITE_{key.upper()}_URL"],
                    pattern=None,
                )
                for key in website_key_names
            }
            for site_config in sites_to_check.values():
                split = urllib.parse.urlsplit(site_config["url"])
                if split.scheme not in ("http", "https"):
                    raise ConfigurationError(
                        f"URL {site_config['url']} is unsupported - only http and https schemes are supported"
                    )

        except Exception as exc:
            if isinstance(exc, ConfigurationError):
                raise
            else:
                raise ConfigurationError(
                    "A URL to check for each website key should be provided in env var WBM_WEBSITE_<UPPERCASE KEY>_URL"
                ) from exc

        for key in sites_to_check.keys():
            pattern_str = os.environ.get(f"WBM_WEBSITE_{key.upper()}_PATTERN")
            if pattern_str:
                try:
                    pattern = re.compile(pattern_str)
                    sites_to_check[key]["pattern"] = pattern
                except Exception as exc:
                    raise ConfigurationError(
                        f"The pattern '{pattern_str}' provided for website '{key}' isn't a valid Python regex"
                    ) from exc
        try:
            check_interval = int(os.environ.get("WBM_CHECK_INTERVAL", "60"))
        except Exception as exc:
            raise ConfigurationError(
                "The time interval in seconds between checks should be provided in env var WBM_CHECK_INTERVAL"
            ) from exc

        if check_interval < 5:
            raise ConfigurationError("The check interval must be at least 5 seconds")

        (
            kafka_bootstrap_servers,
            kakfa_certfile,
            kakfa_keyfile,
            kakfa_cafile,
        ) = kafka_config_from_env()

        return cls(
            sites_to_check={
                key: SiteConfig(url=val["url"], pattern=val.get("pattern")) for key, val in sites_to_check.items()
            },
            check_interval=check_interval,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            kafka_certfile=kakfa_certfile,
            kafka_keyfile=kakfa_keyfile,
            kafka_cafile=kakfa_cafile,
        )
