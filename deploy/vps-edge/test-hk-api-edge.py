#!/usr/bin/env python3
"""Exercise the real Nginx config against isolated HTTPS origins."""
import http.client
import json
import os
import re
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parent
NGINX = os.environ.get("HK_EDGE_TEST_NGINX", shutil.which("nginx") or "nginx")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_GET(self):
        host = self.server.origin_host
        if self.path == "/no-retry":
            self.server.failed_requests += 1
            self.close_connection = True
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "16")
            self.end_headers()
            self.wfile.write(b"data:1\n\n")
            self.wfile.flush()
            time.sleep(0.8)
            self.wfile.write(b"data:2\n\n")
            self.wfile.flush()
            return
        body = json.dumps({
            "origin": host,
            "sni": self.connection.test_sni,
            "headers": dict(self.headers),
        }).encode()
        self.send_response(302 if self.path == "/redirect" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        if self.path == "/redirect":
            self.send_header("Location", f"https://{host}/login")
            self.send_header("Set-Cookie", f"session=test; Domain={host}; Path=/; Secure")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()


def main():
    with tempfile.TemporaryDirectory(prefix="hk-api-edge-test-") as directory:
        tmp = Path(directory)
        (tmp / "logs").mkdir()
        cert, key = tmp / "cert.pem", tmp / "key.pem"
        routes = [
            ("hk-agent3.shyfai.cn", "agent3.shyfai.cn", "hk_api_agent3_origin"),
            ("hk-yy.shagentai.com", "yy.shagentai.com", "hk_api_yy_origin"),
            ("hk-agent.shyfai.com", "agent.shyfai.com", "hk_api_agent_origin"),
        ]
        domains = [host for alias, canonical, _ in routes for host in (canonical, alias)]
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=agent3.shyfai.cn", "-addext",
            "subjectAltName=" + ",".join("DNS:" + host for host in domains),
            "-keyout", str(key), "-out", str(cert),
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        origins = []
        process = None
        try:
            for _, host, _ in routes:
                server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
                server.daemon_threads = True
                server.origin_host, server.failed_requests = host, 0
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(cert, key)
                context.set_servername_callback(lambda sock, name, _: setattr(sock, "test_sni", name))
                server.socket = context.wrap_socket(server.socket, server_side=True)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                origins.append(server)
            http_port, https_port = free_port(), free_port()
            config = (ROOT / "hk-api-edge.conf").read_text()
            for (_, _, pool), origin in zip(routes, origins):
                # YY and agent share a production IP but need distinct TLS
                # keepalive pools; give each its own fixture origin as well.
                config, count = re.subn(
                    r"(upstream " + re.escape(pool) + r" \{\s*server )[^;]+;",
                    lambda m: m.group(1) + f"127.0.0.1:{origin.server_port};",
                    config,
                )
                assert count == 1, pool
            replacements = {
                "listen 80;": f"listen 127.0.0.1:{http_port};",
                "listen [::]:80;": "",
                "listen 443 ssl http2;": f"listen 127.0.0.1:{https_port} ssl http2;",
                "listen [::]:443 ssl http2;": "",
                "/etc/letsencrypt/live/hk-api-edge/fullchain.pem": str(cert),
                "/etc/letsencrypt/live/hk-api-edge/privkey.pem": str(key),
                "/etc/ssl/certs/ca-certificates.crt": str(cert),
                "/var/log/nginx/hk-api-edge.access.log": str(tmp / "access.log"),
                "/var/log/nginx/hk-api-edge.error.log": str(tmp / "error.log"),
            }
            for old, new in replacements.items():
                config = config.replace(old, new)
            main_config = tmp / "nginx.conf"
            main_config.write_text(
                f"daemon off; master_process off; pid {tmp}/nginx.pid;\n"
                f"error_log {tmp}/main-error.log; events {{ worker_connections 128; }}\n"
                f"http {{ access_log off; client_body_temp_path {tmp}/body; proxy_temp_path {tmp}/proxy;\n"
                + config + "\n}\n"
            )
            args = [NGINX, "-p", str(tmp), "-c", str(main_config)]
            subprocess.run(args + ["-t"], check=True)
            process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 5
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", https_port), 0.1):
                        break
                except OSError:
                    if time.monotonic() > deadline or process.poll() is not None:
                        raise RuntimeError((tmp / "main-error.log").read_text())
                    time.sleep(0.03)

            def request(host, path, method="GET", extra=None):
                conn = http.client.HTTPSConnection("127.0.0.1", https_port, context=ssl._create_unverified_context(), timeout=4)
                headers = {"Host": host, **(extra or {})}
                conn.request(method, path, headers=headers)
                response = conn.getresponse()
                return conn, response

            # Alternate hosts repeatedly to catch upstream/SNI keepalive mixups.
            for _ in range(3):
                for alias, canonical, _ in routes:
                    conn, response = request(alias, "/echo?secret=must-not-be-logged", extra={
                        "Origin": f"https://{alias}", "Referer": f"https://{alias}/settings",
                        "Authorization": "Bearer test-only", "Cookie": "test=1",
                        "X-Forwarded-For": "198.51.100.123",
                    })
                    data = json.loads(response.read())
                    assert response.status == 200, data
                    assert data["origin"] == data["sni"] == canonical, data
                    assert data["headers"]["Host"] == canonical
                    assert data["headers"]["Origin"] == f"https://{canonical}"
                    assert data["headers"]["Referer"] == f"https://{canonical}/settings"
                    assert data["headers"]["Authorization"] == "Bearer test-only"
                    assert data["headers"]["Cookie"] == "test=1"
                    assert data["headers"]["X-Forwarded-For"] == "127.0.0.1"
                    assert response.getheader("Access-Control-Allow-Origin") == f"https://{alias}"
                    conn.close()
            for alias, _, _ in routes:
                conn, response = request(alias, "/redirect")
                response.read()
                assert response.status == 302
                assert response.getheader("Location") == f"https://{alias}/login"
                assert f"Domain={alias}" in response.getheader("Set-Cookie")
                conn.close()
                conn, response = request(alias, "/echo", extra={"Origin": "https://external.example"})
                data = json.loads(response.read())
                assert data["headers"]["Origin"] == "https://external.example"
                assert response.getheader("Access-Control-Allow-Origin") == "https://external.example"
                conn.close()
                start = time.monotonic()
                conn, response = request(alias, "/stream")
                assert response.read(8) == b"data:1\n\n"
                assert time.monotonic() - start < 0.6, "SSE was buffered"
                assert response.read() == b"data:2\n\n"
                conn.close()
                conn, response = request(alias, "/no-retry", method="POST")
                response.read()
                assert response.status == 502
                conn.close()
                plain = http.client.HTTPConnection("127.0.0.1", http_port)
                plain.request("POST", "/v1/test?x=1", headers={"Host": alias})
                response = plain.getresponse()
                assert response.status == 308
                assert response.getheader("Location") == f"https://{alias}/v1/test?x=1"
                response.read()
                plain.close()
            assert all(server.failed_requests == 1 for server in origins)
            assert "must-not-be-logged" not in (tmp / "access.log").read_text()
            print("PASS: TLS SNI, host isolation, auth/cookies, CORS, redirects, SSE, no POST retry, HTTP 308, safe logs")
        finally:
            if process is not None:
                process.terminate()
                process.wait(timeout=5)
            for server in origins:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
