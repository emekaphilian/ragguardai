from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from datetime import datetime, timedelta, timezone

import anyio
import httpcore
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ragguard.auth.oidc import _AnyIONetworkBackend, _SafeOIDCTransport


def _certificate(tmp_path, hostname: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{hostname}.pem"
    key_path = tmp_path / f"{hostname}-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return cert_path, key_path


class _LocalDialBackend(httpcore.AsyncNetworkBackend):
    """Route the test's validated public IP to its local TLS test server."""

    def __init__(self, local_port: int):
        self._backend = _AnyIONetworkBackend()
        self.local_port = local_port
        self.dialed_hosts: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.dialed_hosts.append(host)
        assert ipaddress.ip_address(host).is_global
        return await self._backend.connect_tcp(
            "127.0.0.1", self.local_port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise AssertionError("OIDC must not use Unix sockets")

    async def sleep(self, seconds):
        await self._backend.sleep(seconds)


async def _public_test_resolver(host, port, *, type):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))]


def test_transport_reuses_connection_preserves_tls_hostname_and_closes_pool(tmp_path):
    cert_path, key_path = _certificate(tmp_path, "oidc.test")

    async def scenario():
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)
        sni_names: list[str | None] = []
        server_context.set_servername_callback(
            lambda connection, server_name, context: sni_names.append(server_name)
        )
        accepted_connections = 0
        request_count = 0
        connection_closed = asyncio.Event()

        async def handle(reader, writer):
            nonlocal accepted_connections, request_count
            accepted_connections += 1
            try:
                while True:
                    request_head = await reader.readuntil(b"\r\n\r\n")
                    request_count += 1
                    if b"GET /redirect " in request_head:
                        writer.write(
                            b"HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/private\r\n"
                            b"Content-Length: 0\r\nConnection: keep-alive\r\n\r\n"
                        )
                    else:
                        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok")
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, ssl.SSLError):
                    pass
                connection_closed.set()

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
        local_port = server.sockets[0].getsockname()[1]
        client_context = ssl.create_default_context(cafile=str(cert_path))
        backend = _LocalDialBackend(local_port)
        transport = _SafeOIDCTransport(
            network_backend=backend,
            resolver=_public_test_resolver,
            ssl_context=client_context,
        )
        client = httpx.AsyncClient(transport=transport, follow_redirects=False)
        try:
            first = await client.get("https://oidc.test:443/first")
            second = await client.get("https://oidc.test:443/second")
            redirect = await client.get("https://oidc.test:443/redirect")
            assert first.text == second.text == "ok"
            assert redirect.status_code == 302
            assert redirect.headers["location"] == "https://127.0.0.1/private"
            assert accepted_connections == 1
            assert request_count == 3
            assert sni_names == ["oidc.test"]
            assert backend.dialed_hosts == ["93.184.216.34"]
        finally:
            await client.aclose()
            await asyncio.wait_for(connection_closed.wait(), timeout=2)
            server.close()
            await server.wait_closed()

    anyio.run(scenario)


def test_transport_rejects_certificate_for_wrong_hostname(tmp_path):
    cert_path, key_path = _certificate(tmp_path, "different.test")

    async def scenario():
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_path, key_path)

        async def handle(reader, writer):
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, ssl.SSLError):
                pass

        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
        local_port = server.sockets[0].getsockname()[1]
        client_context = ssl.create_default_context(cafile=str(cert_path))
        transport = _SafeOIDCTransport(
            network_backend=_LocalDialBackend(local_port),
            resolver=_public_test_resolver,
            ssl_context=client_context,
        )
        client = httpx.AsyncClient(transport=transport, follow_redirects=False)
        try:
            with pytest.raises(httpx.TransportError):
                await client.get("https://oidc.test:443/")
        finally:
            await client.aclose()
            server.close()
            await server.wait_closed()

    anyio.run(scenario)


def test_transport_connection_failure_does_not_bypass_address_validation():
    class FailingBackend(httpcore.AsyncNetworkBackend):
        attempted_host = None

        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            self.attempted_host = host
            raise httpcore.ConnectError("simulated connection failure")

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            raise AssertionError("OIDC must not use Unix sockets")

        async def sleep(self, seconds):
            return None

    async def scenario():
        backend = FailingBackend()
        transport = _SafeOIDCTransport(network_backend=backend, resolver=_public_test_resolver)
        client = httpx.AsyncClient(transport=transport, follow_redirects=False)
        try:
            with pytest.raises(httpx.TransportError):
                await client.get("https://oidc.test/")
            assert backend.attempted_host == "93.184.216.34"
        finally:
            await client.aclose()

    anyio.run(scenario)


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["93.184.216.34", "10.0.0.8"]])
def test_transport_never_dials_unsafe_or_mixed_dns_answers(addresses):
    class RecordingBackend(httpcore.AsyncNetworkBackend):
        attempted_hosts: list[str] = []

        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            self.attempted_hosts.append(host)
            raise AssertionError("The transport must reject DNS before opening a socket")

        async def connect_unix_socket(self, path, timeout=None, socket_options=None):
            raise AssertionError("OIDC must not use Unix sockets")

        async def sleep(self, seconds):
            return None

    async def resolve(host, port, *, type):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            for address in addresses
        ]

    async def scenario():
        backend = RecordingBackend()
        transport = _SafeOIDCTransport(network_backend=backend, resolver=resolve)
        client = httpx.AsyncClient(transport=transport, follow_redirects=False)
        try:
            with pytest.raises(httpx.TransportError):
                await client.get("https://oidc.test/")
            assert backend.attempted_hosts == []
        finally:
            await client.aclose()

    anyio.run(scenario)
