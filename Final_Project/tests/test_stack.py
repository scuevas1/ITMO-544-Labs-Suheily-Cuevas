"""No-network tests of Python deployment code and policies."""
import json
from pathlib import Path

import pytest

from stack.aws import role_policy
from stack.boot import build_user_data
from stack.config import load_dotenv, settings
from create_weather_stack import ensure_asg, ensure_listener
from budget import estimate


@pytest.fixture
def config(tmp_path):
    src = Path(__file__).resolve().parents[1] / '.env.example'
    target = tmp_path / '.env'
    target.write_text(src.read_text())
    return settings(target)


def test_env_configuration(config):
    assert config['WEATHER_LISTENER_PORT'] == '8080'
    assert config['ADVISOR_LISTENER_PORT'] == '8081'


def test_permissions_are_tier_specific(config):
    topic = 'arn:aws:sns:us-east-2:123456789012:itmo-544-final-email'
    weather = role_policy('weather', config, '123456789012', topic)
    advisor = role_policy('advisor', config, '123456789012', topic)
    for policy in (weather, advisor):
        assert all('*' not in s['Resource'] for s in policy['Statement'])
        assert all('*' not in a for s in policy['Statement'] for a in s['Action'])
    assert 'sns:Publish' not in str(weather)
    assert 'ssm:GetParameter' not in str(weather)
    assert 'sns:Publish' in str(advisor)


def test_python_boot_script_embeds_both_node_apps(config):
    base = Path(__file__).resolve().parents[1]
    for tier in ('weather', 'advisor'):
        data = build_user_data(tier, 'us-east-2', {'PORT':'3000'}, base)
        assert data.startswith('#!/usr/bin/python3')
        assert len(data.encode()) <= 16384
        assert '#!/bin/bash' not in data


def test_budget_is_bounded():
    assert estimate(10, 0.07, 5, 0)['under_two_dollars']
    assert not estimate(40, 0.07, 5, 0)['under_two_dollars']


def test_app_and_deploy_have_no_shell_scripts():
    root = Path(__file__).resolve().parents[1]

    shell_scripts = [
        path for path in root.rglob("*.sh")
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and ".git" not in path.parts
    ]

    assert not shell_scripts
