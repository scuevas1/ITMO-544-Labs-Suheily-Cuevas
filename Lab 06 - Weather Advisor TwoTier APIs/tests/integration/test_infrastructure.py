from pathlib import Path
import socket

import boto3
import pytest
import requests

from stack.config import load_dotenv

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def env():
    return load_dotenv(ROOT / ".env")


@pytest.fixture(scope="module")
def out():
    return load_dotenv(ROOT / "stack_outputs.env")


@pytest.fixture(scope="module")
def clients(env):
    region = env["AWS_REGION"]
    return {
        "elbv2": boto3.client("elbv2", region_name=region),
        "iam": boto3.client("iam", region_name=region),
        "ec2": boto3.client("ec2", region_name=region),
        "asg": boto3.client("autoscaling", region_name=region),
    }


def test_both_target_groups_are_healthy(out, clients):
    for key in ("WEATHER_TG_ARN", "ADVISOR_TG_ARN"):
        targets = clients["elbv2"].describe_target_health(
            TargetGroupArn=out[key]
        )["TargetHealthDescriptions"]

        assert targets
        assert all(
            target["TargetHealth"]["State"] == "healthy"
            for target in targets
        )


def test_apps_are_reachable_through_alb(env, out):
    for port in (
        env["WEATHER_LISTENER_PORT"],
        env["ADVISOR_LISTENER_PORT"]
    ):
        url = f"http://{out['ALB_DNS_NAME']}:{port}/"
        response = requests.get(url, timeout=15)
        assert response.status_code == 200


def test_app_security_group_allows_only_alb(env, out, clients):
    group = clients["ec2"].describe_security_groups(
        GroupIds=[env["APP_SECURITY_GROUP_ID"]]
    )["SecurityGroups"][0]

    rules = [
        rule for rule in group["IpPermissions"]
        if rule.get("FromPort") == 3000
        and rule.get("ToPort") == 3000
    ]

    assert len(rules) == 1
    assert rules[0]["IpRanges"] == []
    assert [
        item["GroupId"]
        for item in rules[0]["UserIdGroupPairs"]
    ] == [out["ALB_SECURITY_GROUP_ID"]]


def test_weather_instance_not_directly_reachable(env, clients):
    groups = clients["asg"].describe_auto_scaling_groups(
        AutoScalingGroupNames=[env["WEATHER_ASG_NAME"]]
    )["AutoScalingGroups"]

    assert len(groups) == 1
    ids = [item["InstanceId"] for item in groups[0]["Instances"]]
    assert ids

    instances = clients["ec2"].describe_instances(
        InstanceIds=ids
    )["Reservations"][0]["Instances"]

    public_ip = instances[0].get("PublicIpAddress")

    if not public_ip:
        return

    try:
        response = requests.get(
            f"http://{public_ip}:3000/",
            timeout=5
        )
    except requests.RequestException:
        return

    pytest.fail(
        f"Application is directly reachable: HTTP {response.status_code}"
    )


def test_database_port_not_publicly_reachable():
    db = load_dotenv(ROOT / "db_outputs.env")
    host = db["DB_HOST"]

    try:
        connection = socket.create_connection((host, 5432), timeout=5)
    except (OSError, TimeoutError):
        return

    connection.close()
    pytest.fail("Database port 5432 is publicly reachable")


def test_iam_roles_have_separate_secret_permissions(env, clients):
    account = boto3.client("sts").get_caller_identity()["Account"]
    prefix = f"arn:aws:ssm:{env['AWS_REGION']}:{account}:parameter"

    db_arn = prefix + env["DB_PASSWORD_PARAM"]
    gemini_arn = prefix + env["GEMINI_PARAM_NAME"]

    cases = [
        (env["WEATHER_ROLE_NAME"], db_arn, gemini_arn),
        (env["ADVISOR_ROLE_NAME"], gemini_arn, db_arn)
    ]

    for role, allowed_arn, denied_arn in cases:
        role_arn = clients["iam"].get_role(
            RoleName=role
        )["Role"]["Arn"]

        for resource, expected in (
            (allowed_arn, "allowed"),
            (denied_arn, "implicitDeny")
        ):
            result = clients["iam"].simulate_principal_policy(
                PolicySourceArn=role_arn,
                ActionNames=["ssm:GetParameter"],
                ResourceArns=[resource]
            )

            assert result["EvaluationResults"][0][
                "EvalDecision"
            ] == expected

