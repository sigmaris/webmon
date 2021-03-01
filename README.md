The code is all contained within one Python package, so the PostgreSQL client psycopg2
is installed as a requirement of the website checker, even though the website checker
doesn't use the database directly. This could be changed if the checker and the database
recorder were split into two packages - or if psycopg2 was made an optional requirement.

https://stackoverflow.com/questions/7370801/how-to-measure-elapsed-time-in-python
https://stackoverflow.com/questions/14592762/a-good-way-to-get-the-charset-encoding-of-an-http-response-in-python

## Installing for local development

1. Create a virtualenv or otherwise isolated Python environment and activate it.
1. Change directory into the root of the project
1. Run `pip install -e .[dev]` to install an editable version of the project in the
   Python environment, with the "dev" extra activated (to pull in the test requirements)

## Running tests in a local environment

The non-integration tests do require PostgreSQL to be installed. They launch and stop
an isolated instance of PostgreSQL for testing.

After performing the above steps to install into a local virtualenv, activate that 
environment and run `pytest` to run all the non-integration tests.

### Integration tests

The integration tests can be enabled by adding the `--inttests` flag to `pytest`.

They require real instances of Kafka and PostgreSQL, and require the following environment variables to be set:

| Name | Value |
| ---- | ----- |
| WBM_KAFKA_BOOT_SERVERS | Comma-separated list of Kafka boot servers in `host:[port]` format |
| WBM_KAFKA_CERTFILE | Path of the client certificate .pem file for Kafka connection |
| WBM_KAFKA_KEYFILE | Path of the client private key .pem file for Kafka connection |
| WBM_KAFKA_CAFILE | Path of the CA certificate .pem file for Kafka connection |
| WBM_DB_CONN_STR | PostgreSQL database connection string or URL of the PostgreSQL database server |

The integration tests should be run on an empty Kafka cluster and an empty PostgreSQL database,
as they create and delete database tables and Kafka topics as part of the test lifecycle!
