"""Kafka and Postgres for the stream tests.

CI provides them as services (TEST_KAFKA_BOOTSTRAP, TEST_DATABASE_URL). Locally
the fixtures start throwaway containers with Docker and remove them after.
"""

import os
import socket
import subprocess
import time
import uuid

import pytest


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(check, what, timeout=90):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except Exception as err:
            if time.monotonic() > deadline:
                raise RuntimeError(f"{what} did not start: {err}") from err
            time.sleep(1)


def container(image, port, inner, env, name):
    try:
        cid = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name, "-p", f"{port}:{inner}"]
            + [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
            + [image],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as err:
        pytest.fail(
            f"stream tests need Docker (or {name.split('-')[1].upper()} via env): {err}"
        )
    return cid


@pytest.fixture(scope="session")
def kafka_bootstrap():
    if url := os.environ.get("TEST_KAFKA_BOOTSTRAP"):
        yield url
        return
    port = free_port()
    cid = container(
        "apache/kafka:3.9.0",
        port,
        9092,
        {
            "KAFKA_NODE_ID": 1,
            "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": "PLAINTEXT://:9092,CONTROLLER://:9093",
            "KAFKA_ADVERTISED_LISTENERS": f"PLAINTEXT://localhost:{port}",
            "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": 1,
            "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": 1,
            "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": 1,
            "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": 0,
        },
        f"sb-kafka-{uuid.uuid4().hex[:6]}",
    )
    from confluent_kafka.admin import AdminClient

    url = f"localhost:{port}"
    admin = AdminClient({"bootstrap.servers": url})
    wait(lambda: admin.list_topics(timeout=2), "Kafka")
    yield url
    subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)


@pytest.fixture(scope="session")
def postgres_admin_url():
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    port = free_port()
    cid = container(
        "postgres:17-alpine",
        port,
        5432,
        {"POSTGRES_PASSWORD": "test", "POSTGRES_USER": "test"},
        f"sb-postgres-{uuid.uuid4().hex[:6]}",
    )
    import psycopg

    url = f"postgresql://test:test@localhost:{port}/postgres"
    wait(lambda: psycopg.connect(url).close(), "Postgres")
    yield url
    subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)


@pytest.fixture
def database_url(postgres_admin_url):
    """A fresh, empty database per test."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(postgres_admin_url, autocommit=True) as conn:
        conn.execute(f"create database {name}")
    return make_conninfo(**{**conninfo_to_dict(postgres_admin_url), "dbname": name})


@pytest.fixture
def kafka_env(kafka_bootstrap, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", kafka_bootstrap)
    monkeypatch.delenv("KAFKA_SASL_MECHANISM", raising=False)
    monkeypatch.setenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
    return kafka_bootstrap
