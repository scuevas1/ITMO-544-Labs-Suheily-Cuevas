"""Real ALB black-box checks. Run explicitly with -m integration."""
import os
import requests
import pytest


@pytest.mark.integration
def test_health_checks():
    advisor = os.environ['ADVISOR_URL']
    weather = os.environ['WEATHER_URL']
    for url in (advisor, weather):
        assert requests.get(url, timeout=10).status_code == 200


@pytest.mark.integration
def test_bad_zip_never_reaches_external_api():
    weather = os.environ['WEATHER_URL']
    response = requests.get(weather+'/weather', params={'zip':'M5V 3L9','date':__import__('datetime').date.today().isoformat()},timeout=10)
    assert response.status_code == 400
