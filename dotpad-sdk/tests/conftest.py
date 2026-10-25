import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dotpad_sdk import DotPad, MockBackend, ViewerServer


def request(url, body=None, *, headers=None):
    options = {"headers": headers or {}}
    if body is not None:
        options["data"] = json.dumps(body).encode()
        options["headers"].setdefault("Content-Type", "application/json")
    try:
        response = urlopen(Request(url, **options), timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        payload = response.read()
        if response.headers["Content-Type"].startswith("application/json"):
            payload = json.loads(payload)
        return response.status, payload


@pytest.fixture
def mock_pad():
    with DotPad(MockBackend()) as pad:
        yield pad


@pytest.fixture
def viewer(mock_pad):
    with ViewerServer(mock_pad, port=0) as server:
        yield server
