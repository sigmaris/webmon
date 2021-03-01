# webmon

This is a system which monitors website availability over a network.

The system consists of two components, the website checker and the database recorder.

For each website to be monitored, an alphanumeric "website key" should be chosen to identify that
website, e.g. "google", "facebook", "sitea" or similar.

The checker component will publish results for each configured website key to a Kafka topic
containing the key, `webmon.<website key>.checkresult`.

The recorder component then consumes on the topics for its configured website keys and stores the
consumed results in a PostgreSQL database.

Due to using separate topics, several instances for checking different websites can coexist using
the same Kafka cluster, as long as they use different website keys. It's also possible to divide
result recording between different instances of the recorder component by giving them different
sets of website keys to consume, or route the results of many checkers running at different intervals
to one recorder by configuring it to record all the checked website keys.

There is an optional command to summarize the logged results for a given day, and delete the logged
results from the database after storing a summary, which can be used to mitigate growth in size
of the table storing the individual logged results - after a month, for example, the daily results
could be summarized and the individual log records deleted, by invoking this command using cron or
a similar approach.

# Installing

The program can be installed as a Python package, or built into a Docker image and run in
a container.

To install as a Python package, use `pip`:

```
pip install git+https://github.com/sigmaris/webmon.git@main
```

To use a Docker container, first check out the repository, change directory into the repository, and build and tag an image:

```
docker build . -t webmon
```

This image tagged "webmon" can then be used to run the checker and recorder components as described below.

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

## Running the checker component

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

# Database recorder component

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

First set the above environment variables, then, once only, initialize the database:

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

To run in a Docker container a volume must be mounted to provide the Kafka SSL files to the container, and
the above environment variables must be passed into the container.

All of the webmon-recorder subcommands described above and in sections below can also be run in a
Docker container by prepending the Docker command and arguments to the webmon-recorder command,
e.g. to run `webmon-recorder initdb` in a Docker container, use:

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

This also goes for the "record", "display" and "rollup" subcommands.

## Displaying recorded results

To display a list of the most recently recorded results in the terminal, use the command:

```
webmon-recorder display
```

This command takes optional flags `--limit N` to limit the results displayed to N rows (the default is 50),
`--date` to display a certain date in the past rather than the latest results, and `--summary` to display
a summary per website key instead of a list of all results.

## Storing summaries and trimming logged results

A daily summary - similar to that displayed by the `--summary` flag to the `display` subcommand - can be
stored in the database, and then the logged results for that day can optionally be deleted to save space.

The command:

```
webmon-recorder rollup
```

will store daily summaries based on all individual logged results in the database. These summaries will then
be used when `webmon-recorder display --summary` is used, instead of calculating the summary on-the-fly.

To summarize and then delete the individual logged results for a given date to save space, use:

```
webmon-recorder rollup --date <YYYY-MM-DD> --trim
```

# Development

## Installing for local development

1. Create a virtualenv or otherwise isolated Python environment and activate it.
1. Change directory into the root of the project
1. Run `pip install -e '.[dev]'` to install an editable version of the project in the
   Python environment, with the "dev" extra activated (to pull in the test requirements)

# Testing

## Running tests in a local environment

The non-integration tests do require PostgreSQL to be installed, though not necessarily running.
They launch and stop an isolated instance of PostgreSQL during the test lifecycle.

After performing the above steps to install into a local virtualenv, activate that 
environment and run `pytest` to run all the non-integration tests.

## Test coverage

Adding `--cov=webmon --cov-report html` arguments to the `pytest` command will produce a HTML
coverage report in the `htmlcov` directory.

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

## Integration tests

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
