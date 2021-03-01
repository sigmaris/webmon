from dataclasses import dataclass, asdict


@dataclass
class CheckResult:
    """
    Represents the result of a check on a website - these are serialised to JSON,
    published to Kafka, deserialised and written into the database.
    """

    check_id: str
    check_time: str
    url: str
    connect_error: str
    response_code: int
    response_time_ms: int
    pattern_matched: bool

    def asdict(self):
        return asdict(self)
