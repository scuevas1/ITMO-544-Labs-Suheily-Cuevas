import time
from pathlib import Path

import subprocess
import boto3
import pytest
import requests

from stack.config import load_dotenv

pytestmark = pytest.mark.chaos
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def lab():
    settings = load_dotenv(ROOT / ".env")
    stack = load_dotenv(ROOT / "stack_outputs.env")
    database = load_dotenv(ROOT / "db_outputs.env")
    session = boto3.Session(region_name=settings["AWS_REGION"])
    dns = stack["ALB_DNS_NAME"]
    return {
        "settings": settings,
        "database": database,
        "ec2": session.client("ec2"),
        "autoscaling": session.client("autoscaling"),
        "ssm": session.client("ssm"),
        "weather": f"http://{dns}:{settings['WEATHER_LISTENER_PORT']}",
        "advisor": f"http://{dns}:{settings['ADVISOR_LISTENER_PORT']}",
    }


def get_json(url, timeout=25):
    try:
        response = requests.get(url, timeout=timeout)
        return response.status_code, response.json()
    except (requests.RequestException, ValueError):
        return None, {}


def weather_instance(lab):
    groups = lab["autoscaling"].describe_auto_scaling_groups(
        AutoScalingGroupNames=[lab["settings"]["WEATHER_ASG_NAME"]]
    )["AutoScalingGroups"]
    assert groups, "Weather Auto Scaling Group not found"
    instances = groups[0]["Instances"]
    active = [item for item in instances if item["LifecycleState"] == "InService"]
    assert active, "No in-service weather instance"
    return active[0]["InstanceId"]


def restart_weather(lab, instance_id):
    response = lab["ec2"].describe_instances(
        InstanceIds=[instance_id]
    )

    instance = response["Reservations"][0]["Instances"][0]
    public_ip = instance["PublicIpAddress"]

    key_name = lab["settings"]["KEY_NAME"]
    key_path = ROOT / f"{key_name}.pem"

    result = subprocess.run(
        [
            "ssh",
            "-i", str(key_path),
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
            f"ec2-user@{public_ip}",
            "sudo systemctl restart weather"
        ],
        capture_output=True,
        text=True,
        timeout=60
    )

    assert result.returncode == 0, (
        f"Weather restart failed: {result.stderr}"
    )

def test_database_outage_keeps_weather_available(lab):
    settings = lab["settings"]
    permission = {
        "IpProtocol": "tcp",
        "FromPort": 5432,
        "ToPort": 5432,
        "UserIdGroupPairs": [{"GroupId": settings["APP_SECURITY_GROUP_ID"]}],
    }
    group_id = lab["database"]["DB_SECURITY_GROUP_ID"]
    instance_id = weather_instance(lab)
    status, _ = get_json(lab["weather"] + "/weather?zip=60616")
    assert status == 200
    revoked = False
    try:
        lab["ec2"].revoke_security_group_ingress(
            GroupId=group_id, IpPermissions=[permission]
        )
        revoked = True
        restart_weather(lab, instance_id)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            status, data = get_json(lab["weather"] + "/weather?zip=98101")
            if status == 200 and data.get("cache") == "unavailable":
                print("Database outage: weather 200, cache unavailable")
                break
            time.sleep(3)
        else:
            pytest.fail("Weather did not return 200 with cache unavailable")
    finally:
        if revoked:
            lab["ec2"].authorize_security_group_ingress(
                GroupId=group_id, IpPermissions=[permission]
            )
            print("Database security group permission restored")


def test_weather_instance_failure_and_recovery(lab):
    instance_id = weather_instance(lab)
    status, _ = get_json(lab["weather"] + "/weather?zip=60616")
    assert status == 200
    lab["autoscaling"].terminate_instance_in_auto_scaling_group(
        InstanceId=instance_id, ShouldDecrementDesiredCapacity=False
    )
    started = time.monotonic()
    saw_502 = False
    recovered_after = None
    deadline = started + 300
    while time.monotonic() < deadline:
        advisor_status, _ = get_json(lab["advisor"] + "/advice?zip=60616", timeout=25)
        if advisor_status == 502:
            saw_502 = True
        weather_status, _ = get_json(lab["weather"] + "/weather?zip=60616", timeout=15)
        if saw_502 and weather_status == 200:
            recovered_after = time.monotonic() - started
            break
        time.sleep(3)
    print(f"Advisor returned 502 during outage: {saw_502}")
    print(f"Weather recovery time: {recovered_after} seconds")
    assert saw_502, "Advisor did not return 502 during the weather outage"
    assert recovered_after is not None, "Weather did not recover within 300 seconds"
