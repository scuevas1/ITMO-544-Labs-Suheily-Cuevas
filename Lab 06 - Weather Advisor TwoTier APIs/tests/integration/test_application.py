from pathlib import Path
import time

import pytest
import requests

from stack.config import load_dotenv

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def urls():
    env = load_dotenv(ROOT / ".env")
    out = load_dotenv(ROOT / "stack_outputs.env")
    dns = out["ALB_DNS_NAME"]

    return {
        "weather": f"http://{dns}:{env['WEATHER_LISTENER_PORT']}",
        "advisor": f"http://{dns}:{env['ADVISOR_LISTENER_PORT']}"
    }


def test_weather_miss_then_hit(urls):
    url = urls["weather"] + "/weather?zip=60616"

    first = requests.get(url, timeout=30)
    assert first.status_code == 200
    assert first.json()["cache"] == "miss"

    second = requests.get(url, timeout=30)
    assert second.status_code == 200
    assert second.json()["cache"] == "hit"


def test_advisor_returns_advice(urls):
    response = requests.get(
        urls["advisor"] + "/advice?zip=60616",
        timeout=60
    )

    assert response.status_code == 200
    assert response.json().get("advice")
    assert response.json().get("source") in ("gemini", "fallback")

def test_weather_history(urls):
    response = requests.get(
        urls["weather"] + "/history",
        timeout=15
    )

    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_weather_invalid_zip(urls):
    response = requests.get(
        urls["weather"] + "/weather?zip=abc",
        timeout=15
    )
    assert response.status_code == 400


def test_weather_unknown_zip(urls):
    response = requests.get(
        urls["weather"] + "/weather?zip=00000",
        timeout=30
    )
    assert response.status_code == 404

def test_advisor_invalid_zip(urls):
    response = requests.get(
        urls["advisor"] + "/advice?zip=abc",
        timeout=15
    )
    assert response.status_code == 400

