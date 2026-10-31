import boto3
import pytest
from moto import mock_aws

from stack.clients import AwsClients
from stack.network import default_vpc_id
from create_database import create_database
from delete_database import delete_database


@pytest.fixture
def database_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")

    with mock_aws():
        region = "us-east-2"
        aws = AwsClients.create(region)
        rds = boto3.client("rds", region_name=region)
        ssm = boto3.client("ssm", region_name=region)

        vpc_id = default_vpc_id(aws)

        app_sg = aws.ec2.create_security_group(
            GroupName="test-app-sg",
            Description="Test application security group",
            VpcId=vpc_id
        )["GroupId"]

        settings = {
            "AWS_REGION": region,
            "AZ_A": "us-east-2a",
            "AZ_B": "us-east-2b",
            "APP_SECURITY_GROUP_ID": app_sg,
            "DB_SG_NAME": "test-weather-db-sg",
            "DB_SUBNET_GROUP_NAME": "test-weather-db-subnets",
            "DB_PASSWORD_PARAM": "/test/weather/db-password",
            "DB_INSTANCE_ID": "test-weather-db",
            "DB_USER": "weatherapp",
            "DB_NAME": "weather",
            "DB_INSTANCE_CLASS": "db.t4g.micro",
            "DB_PORT": "5432"
        }

        yield settings, aws, rds, ssm


def test_database_configuration(database_env):
    settings, aws, rds, ssm = database_env

    create_database(settings, aws, rds, ssm)

    db = rds.describe_db_instances(
        DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
    )["DBInstances"][0]

    assert db["DBInstanceClass"] == "db.t4g.micro"
    assert db["AllocatedStorage"] == 20
    assert db["BackupRetentionPeriod"] == 0
    assert db["MultiAZ"] is False
    assert db["PubliclyAccessible"] is False
    assert db["StorageEncrypted"] is True


def test_database_security_group(database_env):
    settings, aws, rds, ssm = database_env

    create_database(settings, aws, rds, ssm)

    groups = aws.ec2.describe_security_groups(Filters=[
        {
            "Name": "group-name",
            "Values": [settings["DB_SG_NAME"]]
        }
    ])["SecurityGroups"]

    assert len(groups) == 1

    rules = [
        rule
        for rule in groups[0]["IpPermissions"]
        if rule.get("FromPort") == 5432
    ]

    assert len(rules) == 1
    assert rules[0]["ToPort"] == 5432
    assert rules[0]["IpRanges"] == []
    assert rules[0]["UserIdGroupPairs"][0]["GroupId"] == (
        settings["APP_SECURITY_GROUP_ID"]
    )


def test_database_create_delete(database_env):
    settings, aws, rds, ssm = database_env

    create_database(settings, aws, rds, ssm)
    delete_database(settings, aws, rds, ssm)

    assert rds.describe_db_instances()["DBInstances"] == []
    assert rds.describe_db_snapshots()["DBSnapshots"] == []
    assert (
        rds.describe_db_instance_automated_backups()[
            "DBInstanceAutomatedBackups"
        ] == []
    )
    assert ssm.describe_parameters()["Parameters"] == []

    groups = aws.ec2.describe_security_groups(Filters=[
        {
            "Name": "group-name",
            "Values": [settings["DB_SG_NAME"]]
        }
    ])["SecurityGroups"]

    assert groups == []


def test_database_create_twice(database_env):
    settings, aws, rds, ssm = database_env

    create_database(settings, aws, rds, ssm)
    create_database(settings, aws, rds, ssm)

    assert len(rds.describe_db_instances()["DBInstances"]) == 1

    groups = aws.ec2.describe_security_groups(Filters=[
        {
            "Name": "group-name",
            "Values": [settings["DB_SG_NAME"]]
        }
    ])["SecurityGroups"]

    assert len(groups) == 1
    assert len(ssm.describe_parameters()["Parameters"]) == 1


def test_database_delete_twice(database_env):
    settings, aws, rds, ssm = database_env

    create_database(settings, aws, rds, ssm)
    delete_database(settings, aws, rds, ssm)
    delete_database(settings, aws, rds, ssm)

    assert rds.describe_db_instances()["DBInstances"] == []
