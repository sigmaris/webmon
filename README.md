# Installing

The program can be installed as a Python package, or built into a Docker image and run in
a container.

To install as a Python package, use `pip`:

```
pip install git+https://github.com/sigmaris/webmon.git@main
```

To run in a Docker container, first check out the repository, change directory into the repository, and build and tag an image:

```
docker build . -t webmon
```

This image tagged "webmon" can then be used to run the checker and recorder components as described below.

The program consists of two components, the website checker and the database recorder.

# Website checker

This component runs constantly and periodically checks the uptime and response time of a
configured list of websites, and publishes the results to a Kafka topic per site.

It is configured by setting environment variables, as follows:

| Environment variable name | Value |
| ---- | ----- |
| WBM_KAFKA_BOOT_SERVERS | Comma-separated list of Kafka bootstrap servers in `host:[port]` format |
| WBM_KAFKA_CERTFILE | Path of the client certificate .pem file for Kafka connection |
| WBM_KAFKA_KEYFILE | Path of the client private key .pem file for Kafka connection |
| WBM_KAFKA_CAFILE | Path of the CA certificate .pem file for Kafka connection |
| WBM_WEBSITE_KEYS | Comma-separated list of website keys/names, e.g "keya,siteb" |
| WBM_WEBSITE_KEYA_URL, WBM_WEBSITE_SITEB_URL | For each key in WBM_WEBSITE_KEYS there must be a variable of this form supplied containing the URL to check. |
| WBM_WEBSITE_KEYA_PATTERN, WBM_WEBSITE_SITEB_PATTERN | Optionally, for any key in WBM_WEBSITE_KEYS, a Python regex pattern can also be supplied, to check for this pattern in the response. |
| WBM_CHECK_INTERVAL | Optionally specify the interval in seconds to check each site periodically. If not explicitly set, defaults to every 60 seconds |
| WBM_LOGLEVEL | Optionally specify a log level e.g. DEBUG. Defaults to INFO if not explicitly set. |

## Running the checker

After setting the above environment variables, run the website checker if installed as a Python package with the command:

```
webmon-checker
```

Alternatively, to run in a Docker container a volume must be mounted to provide the Kafka SSL files to the container, and
the above environment variables must be passed into the container:

```
# Adjust the path where your Kafka certs are located, and the other environment variables described above, as appropriate
docker run \
  -v /path/to/kafka/cert/dir:/certificates \
  -e WBM_KAFKA_BOOT_SERVERS \
  -e WBM_KAFKA_CERTFILE=/certificates/kafka_cert.pem \
  -e WBM_KAFKA_KEYFILE=/certificates/kafka_privkey.pem \
  -e WBM_KAFKA_CAFILE=/certificates/kafka_cafile.pem \
  -e WBM_WEBSITE_KEYS \
  -e WBM_WEBSITE_KEYA_URL \
  -e WBM_WEBSITE_SITEB_URL \
  webmon webmon-checker
```

# Database recorder

This component runs constantly, consuming Kafka messages published by the website checker
component. Upon receipt of a message it records it in a PostgreSQL database.

It is configured by setting environment variables, as follows:

| Environment variable name | Value |
| ---- | ----- |
| WBM_KAFKA_BOOT_SERVERS | Comma-separated list of Kafka bootstrap servers in `host:[port]` format |
| WBM_KAFKA_CERTFILE | Path of the client certificate .pem file for Kafka connection |
| WBM_KAFKA_KEYFILE | Path of the client private key .pem file for Kafka connection |
| WBM_KAFKA_CAFILE | Path of the CA certificate .pem file for Kafka connection |
| WBM_WEBSITE_KEYS | Comma-separated list of website keys/names to subscribe for results on Kafka, e.g "keya,siteb". This should match the list supplied to the checker component. |
| WBM_DB_CONN_STR | PostgreSQL database connection string or URL of the PostgreSQL database server |
| WBM_LOGLEVEL | Optionally specify a log level e.g. DEBUG. Defaults to INFO if not explicitly set. |

## Running the recorder

### Running if installed as a Python package

First set the above environment variables then, once only, initialize the database:

```
webmon-recorder initdb
```

This will create the database tables used for storing results.

Then, run the website checker component as above, which will create the topics in Kafka.

Then, run the recorder component in recording mode:

```
webmon-recorder record
```

### Running in a Docker container

Alternatively, to run in a Docker container a volume must be mounted to provide the Kafka SSL files to the container, and
the above environment variables must be passed into the container. To initialise the database:

```
# Adjust the path where your Kafka certs are located, and the other environment variables described above, as appropriate
docker run \
  -v /path/to/kafka/cert/dir:/certificates \
  -e WBM_KAFKA_BOOT_SERVERS \
  -e WBM_KAFKA_CERTFILE=/certificates/kafka_cert.pem \
  -e WBM_KAFKA_KEYFILE=/certificates/kafka_privkey.pem \
  -e WBM_KAFKA_CAFILE=/certificates/kafka_cafile.pem \
  -e WBM_WEBSITE_KEYS \
  -e WBM_DB_CONN_STR \
  webmon webmon-recorder initdb
```

Then, after the checker is running, to run the recorder component in recording mode:

```
# Adjust the path where your Kafka certs are located, and the other environment variables described above, as appropriate
docker run \
  -v /path/to/kafka/cert/dir:/certificates \
  -e WBM_KAFKA_BOOT_SERVERS \
  -e WBM_KAFKA_CERTFILE=/certificates/kafka_cert.pem \
  -e WBM_KAFKA_KEYFILE=/certificates/kafka_privkey.pem \
  -e WBM_KAFKA_CAFILE=/certificates/kafka_cafile.pem \
  -e WBM_WEBSITE_KEYS \
  -e WBM_DB_CONN_STR \
  webmon webmon-recorder record
```

# Design

The code is all contained within one Python package, so the PostgreSQL client psycopg2
is installed as a requirement of the website checker, even though the website checker
doesn't use the database directly. This could be changed if the checker and the database
recorder were split into two packages - or if psycopg2 was made an optional requirement.

https://stackoverflow.com/questions/7370801/how-to-measure-elapsed-time-in-python
https://stackoverflow.com/questions/14592762/a-good-way-to-get-the-charset-encoding-of-an-http-response-in-python

## Installing for local development

1. Create a virtualenv or otherwise isolated Python environment and activate it.
1. Change directory into the root of the project
1. Run `pip install -e '.[dev]'` to install an editable version of the project in the
   Python environment, with the "dev" extra activated (to pull in the test requirements)

## Running tests in a local environment

The non-integration tests do require PostgreSQL to be installed, though not necessarily running.
They launch and stop an isolated instance of PostgreSQL during the test lifecycle.

After performing the above steps to install into a local virtualenv, activate that 
environment and run `pytest` to run all the non-integration tests.

## Running tests in a Docker container

Build a Docker image with the program and also testing dependencies installed:

```
docker build -f Dockerfile.tests . -t webmon-tests
```

Then run the tests inside a container based on that image:

```
docker run webmon-tests pytest
```

If the source code has changed locally, the updated code can be installed into the container
and tests re-run quickly, instead of rebuilding the whole image:

```
docker run -v $(pwd):/src webmon-tests bash -c "pip3.7 install -e '.[dev]' && pytest"
```


### Integration tests

The integration tests can be enabled by adding the `--inttests` flag to `pytest`.

They require real instances of Kafka and PostgreSQL, and require the following environment variables to be set:

| Name | Value |
| ---- | ----- |
| WBM_KAFKA_BOOT_SERVERS | Comma-separated list of Kafka bootstrap servers in `host:[port]` format |
| WBM_KAFKA_CERTFILE | Path of the client certificate .pem file for Kafka connection |
| WBM_KAFKA_KEYFILE | Path of the client private key .pem file for Kafka connection |
| WBM_KAFKA_CAFILE | Path of the CA certificate .pem file for Kafka connection |
| WBM_DB_CONN_STR | PostgreSQL database connection string or URL of the PostgreSQL database server |

The integration tests should be run on an empty Kafka cluster and an empty PostgreSQL database,
as they create and delete database tables and Kafka topics as part of the test lifecycle!

Integration tests can also be run in a Docker container:

```
# Adjust the path where your Kafka certs are located as appropriate
docker run \
  -v /path/to/kafka/cert/dir:/certificates \
  -e WBM_KAFKA_BOOT_SERVERS \
  -e WBM_KAFKA_CERTFILE=/certificates/kafka_cert.pem \
  -e WBM_KAFKA_KEYFILE=/certificates/kafka_privkey.pem \
  -e WBM_KAFKA_CAFILE=/certificates/kafka_cafile.pem \
  -e WBM_DB_CONN_STR \
  webmon-tests pytest --inttests
```
