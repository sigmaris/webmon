def pytest_addoption(parser):
    parser.addoption(
        "--inttests",
        action="store_true",
        dest="inttests",
        default=False,
        help="Enable integration tests requiring a real Kafka cluster and PostgreSQL server",
    )
