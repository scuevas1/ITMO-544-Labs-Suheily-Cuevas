import base64
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import create_weather_stack as weather_stack
from stack.clients import AwsClients
from stack.network import default_vpc_id


@pytest.fixture
def weather_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setattr(weather_stack.time, "sleep", lambda _: None)

    for name in ("weather-app", "advisor-app"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "app.js").write_text(
            f"console.log('{name}');\n"
        )
        (folder / "package.json").write_text(
            json.dumps({"name": name, "version": "1.0.0"})
        )

    with mock_aws():
        region = "us-east-2"
        aws = AwsClients.create(region)
        session = boto3.session.Session(region_name=region)
        ssm = session.client("ssm")
        sts = session.client("sts")

        vpc_id = default_vpc_id(aws)

        app_sg = aws.ec2.create_security_group(
            GroupName="test-weather-app-sg",
            Description="Application security group",
            VpcId=vpc_id
        )["GroupId"]

        aws.ec2.authorize_security_group_ingress(
            GroupId=app_sg,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 3000,
                "ToPort": 3000,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
            }]
        )

        aws.ec2.create_key_pair(KeyName="test-key")
        ami = aws.ec2.describe_images()["Images"][0]["ImageId"]

        settings = {
            "AWS_REGION": region,
            "AZ_A": "us-east-2a",
            "AZ_B": "us-east-2b",
            "AMI_ID": ami,
            "INSTANCE_TYPE": "t3.micro",
            "KEY_NAME": "test-key",
            "APP_SECURITY_GROUP_ID": app_sg,
            "WEATHER_ROLE_NAME": "test-weather-role",
            "WEATHER_PROFILE_NAME": "test-weather-profile",
            "WEATHER_LT_NAME": "test-weather-lt",
            "WEATHER_TG_NAME": "test-weather-tg",
            "WEATHER_ASG_NAME": "test-weather-asg",
            "WEATHER_LISTENER_PORT": "8080",
            "ADVISOR_ROLE_NAME": "test-advisor-role",
            "ADVISOR_PROFILE_NAME": "test-advisor-profile",
            "ADVISOR_LT_NAME": "test-advisor-lt",
            "ADVISOR_TG_NAME": "test-advisor-tg",
            "ADVISOR_ASG_NAME": "test-advisor-asg",
            "ADVISOR_LISTENER_PORT": "8081",
            "ALB_NAME": "test-weather-alb",
            "ALB_SG_NAME": "test-weather-alb-sg",
            "DB_PASSWORD_PARAM": "/test/db-password",
            "GEMINI_PARAM_NAME": "/test/gemini-api-key",
            "DB_NAME": "weather",
            "DB_USER": "weatherapp",
            "CACHE_SECONDS": "600",
            "CONTACT_EMAIL": "test@example.com",
            "GEMINI_MODEL": "test-model",
            "KEY_CACHE_SECONDS": "60"
        }

        ssm.put_parameter(
            Name=settings["DB_PASSWORD_PARAM"],
            Type="SecureString",
            Value="unit-test-password"
        )

        ssm.put_parameter(
            Name=settings["GEMINI_PARAM_NAME"],
            Type="SecureString",
            Value="unit-test-key"
        )

        Path("db_outputs.env").write_text(
            "DB_HOST=test-db.example.amazonaws.com\n"
            "DB_SECURITY_GROUP_ID=sg-test\n"
        )

        yield settings, aws, ssm, sts


def policy_statement(aws, role):
    response = aws.iam.get_role_policy(
        RoleName=role,
        PolicyName=f"{role}-policy"
    )

    document = response["PolicyDocument"]

    if isinstance(document, str):
        document = json.loads(document)

    return document["Statement"][0]


def user_data(aws, name):
    template = aws.ec2.describe_launch_template_versions(
        LaunchTemplateName=name
    )["LaunchTemplateVersions"][-1]

    encoded = template["LaunchTemplateData"]["UserData"]
    return base64.b64decode(encoded).decode()


def test_each_role_can_read_only_its_own_secret(weather_env):
    settings, aws, ssm, sts = weather_env

    weather_stack.create_weather_stack(settings, aws, ssm, sts)

    account = sts.get_caller_identity()["Account"]
    prefix = f"arn:aws:ssm:us-east-2:{account}:parameter"

    weather_policy = policy_statement(
        aws, settings["WEATHER_ROLE_NAME"]
    )

    advisor_policy = policy_statement(
        aws, settings["ADVISOR_ROLE_NAME"]
    )

    assert weather_policy["Action"] == ["ssm:GetParameter"]
    assert advisor_policy["Action"] == ["ssm:GetParameter"]

    assert weather_policy["Resource"] == (
        prefix + settings["DB_PASSWORD_PARAM"]
    )

    assert advisor_policy["Resource"] == (
        prefix + settings["GEMINI_PARAM_NAME"]
    )

    assert settings["GEMINI_PARAM_NAME"] not in json.dumps(
        weather_policy
    )

    assert settings["DB_PASSWORD_PARAM"] not in json.dumps(
        advisor_policy
    )


def test_alb_first_and_correct_user_data(weather_env, monkeypatch):
    settings, aws, ssm, sts = weather_env
    order = []

    original_alb = weather_stack.ensure_load_balancer
    original_template = weather_stack.ensure_launch_template

    def record_alb(*args, **kwargs):
        result = original_alb(*args, **kwargs)
        order.append("alb")
        return result

    def record_template(*args, **kwargs):
        order.append("template")
        return original_template(*args, **kwargs)

    monkeypatch.setattr(
        weather_stack, "ensure_load_balancer", record_alb
    )

    monkeypatch.setattr(
        weather_stack, "ensure_launch_template", record_template
    )

    weather_stack.create_weather_stack(settings, aws, ssm, sts)

    assert order[0] == "alb"
    assert order.count("template") == 2

    outputs = dict(
        line.split("=", 1)
        for line in Path("stack_outputs.env").read_text().splitlines()
    )

    advisor_data = user_data(
        aws, settings["ADVISOR_LT_NAME"]
    )

    weather_data = user_data(
        aws, settings["WEATHER_LT_NAME"]
    )

    assert outputs["ALB_DNS_NAME"] in advisor_data
    assert "test-db.example.amazonaws.com" in weather_data
    assert "unit-test-password" not in weather_data
    assert "unit-test-key" not in advisor_data


def test_both_user_data_scripts_are_under_16_kb(weather_env):
    settings, aws, ssm, sts = weather_env

    weather_stack.create_weather_stack(settings, aws, ssm, sts)

    for name in (
        settings["WEATHER_LT_NAME"],
        settings["ADVISOR_LT_NAME"]
    ):
        data = user_data(aws, name)
        assert len(data.encode()) <= 16384


def test_creating_weather_stack_twice_has_no_duplicate_resources(weather_env):
    settings, aws, ssm, sts = weather_env

    weather_stack.create_weather_stack(settings, aws, ssm, sts)
    weather_stack.create_weather_stack(settings, aws, ssm, sts)

    assert len(
        aws.elbv2.describe_load_balancers()["LoadBalancers"]
    ) == 1

    assert len(
        aws.elbv2.describe_target_groups()["TargetGroups"]
    ) == 2

    assert len(
        aws.autoscaling.describe_auto_scaling_groups()[
            "AutoScalingGroups"
        ]
    ) == 2

    for name in (
        settings["WEATHER_LT_NAME"],
        settings["ADVISOR_LT_NAME"]
    ):
        templates = aws.ec2.describe_launch_templates(
            LaunchTemplateNames=[name]
        )["LaunchTemplates"]
        assert len(templates) == 1

    groups = aws.ec2.describe_security_groups(Filters=[
        {
            "Name": "group-name",
            "Values": [settings["ALB_SG_NAME"]]
        }
    ])["SecurityGroups"]

    assert len(groups) == 1
