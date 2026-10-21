"""Kafka client config from env vars only: local Kafka now, Azure Event Hubs later.

Local (compose):   KAFKA_BOOTSTRAP_SERVERS=localhost:9092   (the default)
Event Hubs:        KAFKA_BOOTSTRAP_SERVERS=<namespace>.servicebus.windows.net:9093
                   KAFKA_SECURITY_PROTOCOL=SASL_SSL
                   KAFKA_SASL_MECHANISM=PLAIN
                   KAFKA_SASL_USERNAME=$ConnectionString
                   KAFKA_SASL_PASSWORD=<the namespace connection string>
"""

import os

TOPIC = os.environ.get("KAFKA_TOPIC", "match-events")

# Message header "contract": what the value is. Same topic and key (match_id),
# so a match's header, events and end marker stay in order.
MATCH, EVENT, END = b"Match", b"MatchEvent", b"MatchEnd"
SENT_AT = "sent_at_ns"  # header: producer wall clock, for latency


def config(**extra) -> dict:
    cfg = {
        "bootstrap.servers": os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        ),
        "security.protocol": os.environ.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"),
    }
    if mechanism := os.environ.get("KAFKA_SASL_MECHANISM"):
        cfg["sasl.mechanism"] = mechanism
        cfg["sasl.username"] = os.environ["KAFKA_SASL_USERNAME"]
        cfg["sasl.password"] = os.environ["KAFKA_SASL_PASSWORD"]
    cfg.update(extra)
    return cfg


def ensure_topic(topic: str = TOPIC, partitions: int = 1) -> None:
    """Create the topic on local Kafka. On Event Hubs the event hub is made by
    infra (Bicep), so this is skipped there."""
    if config()["security.protocol"] != "PLAINTEXT":
        return
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient(config())
    if topic in admin.list_topics(timeout=10).topics:
        return
    for f in admin.create_topics([NewTopic(topic, partitions, 1)]).values():
        try:
            f.result()
        except Exception as err:  # created meanwhile by someone else
            if "TOPIC_ALREADY_EXISTS" not in str(err):
                raise


def header(msg, name: str) -> bytes | None:
    return dict(msg.headers() or []).get(name)
