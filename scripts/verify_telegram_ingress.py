"""Verify isolated HTTP intake, real issuer JWT, Redis/Celery and recovery.

Requires explicit TEST_DATABASE_URL and TEST_AUTH_DATABASE_URL ending _test,
the sibling AuthFortress virtualenv, Docker, and a built --image. Creates fresh
test databases and uniquely named containers; retains databases/stopped containers.
Telegram setup and AgentHub admission use controlled HTTP receivers. No live bot
or LLM credentials are read. Never run this factory as the normal service app.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
from cryptography.fernet import Fernet
from psycopg import sql
from sqlalchemy.engine import make_url


def create_smoke_app():
    """Built-image factory overriding only the Telegram HTTP boundary."""
    from src.api.main import app
    from src.api.v1.dependencies.platform import get_telegram
    from src.infrastructure.platform.clients import TelegramClient

    def provider(request):
        method = request.url.path.rsplit("/", 1)[-1]
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.post(
                os.environ["CONTROLLED_PROVIDER_URL"] + "/controlled/" + method,
                json=json.loads(request.content) if request.content else {},
            )
        return httpx.Response(response.status_code, json=response.json())

    app.dependency_overrides[get_telegram] = lambda: TelegramClient(
        transport=httpx.MockTransport(provider)
    )
    return app


def run(args, *, env=None, cwd=None):
    result = subprocess.run(args, env=env, cwd=cwd, capture_output=True, timeout=120)
    if result.returncode:
        # Child output may contain connection details; never relay it.
        raise RuntimeError("Controlled verification command failed: " + args[0])
    return result.stdout.decode().strip()


def fresh_database(value, name):
    url = make_url(value)
    if not (url.database or "").endswith("_test") or url.host not in {
        "127.0.0.1",
        "localhost",
    }:
        raise ValueError("Explicit local test database required")
    params = dict(
        host=url.host, port=url.port, user=url.username, password=url.password
    )
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return url.set(database=name)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (httpx.HTTPError, psycopg.OperationalError):
            pass
        time.sleep(0.2)
    raise AssertionError("Controlled verification deadline exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="webhook-verification:local")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    auth_root = root.parent / "AuthFortress"
    auth_python = auth_root / ".venv" / "Scripts" / "python.exe"
    if not auth_python.exists():
        auth_python = auth_root / ".venv" / "bin" / "python"
    identifier = uuid4().hex
    webhook_url = fresh_database(
        os.environ["TEST_DATABASE_URL"], f"nexus_ingress_{identifier}_test"
    )
    auth_url = fresh_database(
        os.environ["TEST_AUTH_DATABASE_URL"], f"nexus_ingress_auth_{identifier}_test"
    )
    db_params = dict(
        host=webhook_url.host,
        port=webhook_url.port,
        user=webhook_url.username,
        password=webhook_url.password,
        dbname=webhook_url.database,
    )
    auth_key, ingress_key, context_key = (secrets.token_urlsafe(32) for _ in range(3))
    cipher_key = Fernet.generate_key().decode()
    provider_id = uuid4().int % 2**50
    auth_port, api_port = free_port(), free_port()
    containers = []
    process = None
    server = None
    log_file = None
    provider_calls = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            decoded = json.loads(body)
            if self.path.startswith("/controlled/"):
                provider_calls.append((self.path, decoded))
                receipt = {
                    "ok": True,
                    "result": True
                    if self.path.endswith("setWebhook")
                    else {
                        "id": provider_id,
                        "is_bot": True,
                        "username": "controlled_bot",
                    },
                }
                status = 200
            else:
                import hashlib
                import hmac

                expected = (
                    "sha256="
                    + hmac.new(ingress_key.encode(), body, hashlib.sha256).hexdigest()
                )
                assert self.path == "/internal/v1/telegram/updates"
                assert hmac.compare_digest(
                    self.headers["X-Webhook-Signature"], expected
                )
                assert not any(
                    self.headers.get(key)
                    for key in ("Authorization", "Cookie", "X-API-Key")
                )
                with psycopg.connect(**db_params) as connection:
                    connection.execute(
                        "INSERT INTO verification_receiver.receipts (event_id,job_id) "
                        "VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (UUID(decoded["event_id"]), uuid4()),
                    )
                    job = connection.execute(
                        "UPDATE verification_receiver.receipts SET calls=calls+1 "
                        "WHERE event_id=%s RETURNING job_id,calls",
                        (UUID(decoded["event_id"]),),
                    ).fetchone()
                receipt = {
                    "event_id": decoded["event_id"],
                    "job_id": str(job[0]),
                    "state": "pending",
                }
                status = (
                    500 if job[1] == 1 else 200
                )  # Durable admission, lost first receipt.
            data = json.dumps(receipt).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    def container(name, command, environment=None, publish=None):
        full_name = "ingress-verify-" + identifier[:12] + "-" + name
        options = [
            "docker",
            "run",
            "-d",
            "--name",
            full_name,
            "--add-host",
            "auth_service:host-gateway",
            "--add-host",
            "agent_service:host-gateway",
        ]
        if publish:
            options += ["-p", publish]
        for key in environment or {}:
            options += ["--env", key]
        run(options + command, env={**os.environ, **(environment or {})})
        containers.append(full_name)
        return full_name

    try:
        broker_port = free_port()
        broker = container(
            "redis", ["redis:7-alpine"], publish=f"127.0.0.1:{broker_port}:6379"
        )
        base_env = {
            **os.environ,
            "DATABASE_URL": webhook_url.set(
                drivername="postgresql+asyncpg"
            ).render_as_string(hide_password=False),
            "REDIS_URL": f"redis://127.0.0.1:{broker_port}/0",
            "CELERY_BROKER_URL": f"redis://127.0.0.1:{broker_port}/0",
            "SECRET_KEY": secrets.token_urlsafe(32),
            "PLATFORM_BOTS_ENABLED": "false",
            "PLATFORM_TELEGRAM_ENABLED": "false",
        }
        run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=base_env, cwd=root
        )
        run([sys.executable, "-m", "alembic", "check"], env=base_env, cwd=root)
        auth_env = {
            **os.environ,
            "DATABASE_URL": auth_url.set(
                drivername="postgresql+psycopg2"
            ).render_as_string(hide_password=False),
            "REDIS_URL": "redis://127.0.0.1:56379/12",
            "JWT_SECRET_KEY": secrets.token_urlsafe(32),
            "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": auth_key,
        }
        run(
            [str(auth_python), "-m", "alembic", "upgrade", "head"],
            env=auth_env,
            cwd=auth_root,
        )
        log_file = (root / ".venv" / ("ingress-verify-" + identifier + ".log")).open(
            "wb"
        )
        process = subprocess.Popen(
            [
                str(auth_python),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(auth_port),
            ],
            env=auth_env,
            cwd=auth_root,
            stdout=log_file,
            stderr=log_file,
        )
        with psycopg.connect(**db_params) as connection:
            connection.execute("CREATE SCHEMA verification_receiver")
            connection.execute(
                "CREATE TABLE verification_receiver.receipts("
                "event_id uuid PRIMARY KEY, "
                "job_id uuid NOT NULL UNIQUE, calls integer NOT NULL DEFAULT 0)"
            )
        server = ThreadingHTTPServer(("0.0.0.0", 0), Receiver)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        receiver_port = server.server_address[1]
        runtime = {
            "DATABASE_URL": webhook_url.set(
                drivername="postgresql+asyncpg", host="host.docker.internal"
            ).render_as_string(hide_password=False),
            "REDIS_URL": f"redis://host.docker.internal:{broker_port}/0",
            "CELERY_BROKER_URL": f"redis://host.docker.internal:{broker_port}/0",
            "SECRET_KEY": base_env["SECRET_KEY"],
            "PLATFORM_BOTS_ENABLED": "false",
            "PLATFORM_TELEGRAM_ENABLED": "false",
            "AUTHFORTRESS_BASE_URL": f"http://auth_service:{auth_port}",
            "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": auth_key,
            "AGENTHUB_BASE_URL": f"http://agent_service:{receiver_port}",
            "WEBHOOK_AGENT_INGRESS_KEY": ingress_key,
            "PLATFORM_PUBLICATION_MAX_ATTEMPTS": "3",
        }
        api_env = {
            **runtime,
            "PLATFORM_BOTS_ENABLED": "true",
            "PLATFORM_TELEGRAM_ENABLED": "true",
            "BOT_CREDENTIALS_KEY": cipher_key,
            "WEBHOOK_AGENT_CONTEXT_KEY": context_key,
            "TELEGRAM_WEBHOOK_ORIGIN": "https://demo.example.com",
            "CONTROLLED_PROVIDER_URL": f"http://host.docker.internal:{receiver_port}",
        }
        container(
            "api",
            [
                args.image,
                "uvicorn",
                "scripts.verify_telegram_ingress:create_smoke_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            api_env,
            f"127.0.0.1:{api_port}:8000",
        )
        with (
            httpx.Client(
                base_url=f"http://127.0.0.1:{auth_port}", timeout=15, trust_env=False
            ) as auth,
            httpx.Client(
                base_url=f"http://127.0.0.1:{api_port}", timeout=15, trust_env=False
            ) as api,
        ):
            wait_for(lambda: auth.get("/health").status_code == 200)
            wait_for(lambda: api.get("/health/ready").status_code == 200)
            account = {
                "email": f"ingress-{identifier}@example.com",
                "username": "ingress",
                "password": "Aa1!" + secrets.token_urlsafe(24),
            }
            assert auth.post("/api/v1/auth/register", json=account).status_code == 200
            login = auth.post("/api/v1/auth/login", json=account)
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            tenant = auth.post(
                "/api/v1/tenants",
                json={"name": "Ingress verification"},
                headers=headers,
            )
            assert tenant.status_code == 201
            route = "/api/v1/tenants/" + tenant.json()["id"] + "/bots"
            bot = api.post(
                route,
                headers=headers,
                json={
                    "name": "Controlled bot",
                    "token": "123456:fictional-verification-token",
                },
            )
            assert bot.status_code == 201
            bot_path = route + "/" + bot.json()["id"]
            assert (
                api.post(
                    bot_path + "/webhook", headers=headers, json={"dry_run": True}
                ).status_code
                == 200
            )
            assert not any(path.endswith("setWebhook") for path, _ in provider_calls)
            assert (
                api.post(
                    bot_path + "/webhook", headers=headers, json={"dry_run": False}
                ).status_code
                == 200
            )
            setup = [
                body for path, body in provider_calls if path.endswith("setWebhook")
            ]
            assert len(setup) == 1
            telegram_headers = {
                "X-Telegram-Bot-Api-Secret-Token": setup[0]["secret_token"]
            }
            intake = "/webhooks/telegram/" + bot.json()["id"]
            payload = {
                "update_id": 42,
                "message": {
                    "message_id": 9,
                    "chat": {"id": 17, "type": "private"},
                    "text": "Hello",
                },
            }
            run(["docker", "stop", broker])
            admitted = api.post(intake, headers=telegram_headers, json=payload)
            assert admitted.status_code == 202
            event_id = UUID(admitted.json()["event_id"])
            with psycopg.connect(**db_params) as connection:
                row = connection.execute(
                    "SELECT state,attempts FROM platform_ingress_outbox "
                    "WHERE ingress_id=%s",
                    (event_id,),
                ).fetchone()
                assert row == ("pending", 0)
            scanner = container(
                "scanner",
                [args.image, "python", "-m", "scripts.recover_platform_outbox"],
                runtime,
            )
            run(["docker", "start", broker])
            container(
                "worker",
                [
                    args.image,
                    "celery",
                    "-A",
                    "src.infrastructure.queue.celery_app",
                    "worker",
                    "--loglevel=warning",
                    "--concurrency=1",
                ],
                runtime,
            )

            def published():
                with psycopg.connect(**db_params) as connection:
                    row = connection.execute(
                        "SELECT state,attempts,published_job_id "
                        "FROM platform_ingress_outbox WHERE ingress_id=%s",
                        (event_id,),
                    ).fetchone()
                    receipt = connection.execute(
                        "SELECT job_id,calls FROM verification_receiver.receipts "
                        "WHERE event_id=%s",
                        (event_id,),
                    ).fetchone()
                    return (
                        row[0] == "published"
                        and row[1] == 2
                        and receipt
                        and row[2] == receipt[0]
                        and receipt[1] == 2
                    )

            wait_for(published, 60)
            run(
                [
                    "docker",
                    "exec",
                    scanner,
                    "python",
                    "-m",
                    "scripts.recover_platform_outbox",
                    "--once",
                ]
            )
            replay = api.post(intake, headers=telegram_headers, json=payload)
            assert replay.status_code == 200 and replay.json()["event_id"] == str(
                event_id
            )
            changed = {**payload, "message": {**payload["message"], "text": "Changed"}}
            assert (
                api.post(intake, headers=telegram_headers, json=changed).status_code
                == 409
            )
            assert api.post(intake, content=b"invalid").status_code == 401
            inactive = api.post(bot_path + "/deactivate", headers=headers)
            assert inactive.status_code == 200 and inactive.json()["is_active"] is False
            assert (
                api.post(
                    intake, headers=telegram_headers, json={"update_id": 43}
                ).status_code
                == 403
            )
        print(
            "PASS: real JWT/owner setup, dry-run, built API/worker/scanner, "
            "broker outage admission, recovery, lost receipt replay, one durable job, "
            "duplicate/conflict, inactive rejection"
        )
        print(
            "Retained test databases: "
            + webhook_url.database
            + ", "
            + auth_url.database
        )
    finally:
        for name in reversed(containers):
            run(["docker", "stop", name])
        if server:
            server.shutdown()
            server.server_close()
        if process:
            process.terminate()
            process.wait(timeout=15)
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()
