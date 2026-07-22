"""Regression: SSRF guard blocks internal/metadata targets (docs/06 §3, docs/08 §3)."""

import pytest

from app.agent.net_guard import SSRFBlocked, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # AWS IMDS
        "http://metadata.google.internal/",  # GCP metadata (resolves internal)
        "http://127.0.0.1:6379/",  # local Redis
        "http://localhost:8000/",  # local API
        "http://10.0.0.5/",  # RFC1918
        "http://192.168.1.1/",  # RFC1918
        "http://[::1]/",  # IPv6 loopback
        "http://100.64.0.1/",  # CGNAT
        "ftp://example.com/",  # bad scheme
        "http://user:pass@example.com/",  # userinfo
        "http://example.com:22/",  # bad port
    ],
)
def test_forbidden_urls_are_blocked(url):
    with pytest.raises(SSRFBlocked):
        validate_url(url)


def test_public_https_is_allowed():
    ips = validate_url("https://example.com/")
    assert ips  # resolved to at least one public IP
