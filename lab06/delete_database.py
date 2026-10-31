#!/usr/bin/env python3

import boto3
from pathlib import Path
from botocore.exceptions import ClientError

from stack.clients import AwsClients
from stack.config import load_dotenv
from stack.network import default_vpc_id
from stack.util import error_code, retry_on


def delete_database(settings, aws, rds, ssm):
    print("== Deleting the database ==")

    try:
        rds.describe_db_instances(
            DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
        )
    except ClientError as err:
        if error_code(err) not in (
            "DBInstanceNotFound",
            "DBInstanceNotFoundFault"
        ):
            raise
        print("Database not found, nothing to delete.")
    else:
        rds.delete_db_instance(
            DBInstanceIdentifier=settings["DB_INSTANCE_ID"],
            SkipFinalSnapshot=True,
            DeleteAutomatedBackups=True
        )

        print("Waiting for the database to be deleted...")

        rds.get_waiter("db_instance_deleted").wait(
            DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
        )

    print("== Deleting the DB subnet group ==")

    try:
        rds.delete_db_subnet_group(
            DBSubnetGroupName=settings["DB_SUBNET_GROUP_NAME"]
        )
    except ClientError as err:
        if error_code(err) != "DBSubnetGroupNotFoundFault":
            raise

    print("== Deleting the database security group ==")

    vpc_id = default_vpc_id(aws)

    groups = aws.ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [settings["DB_SG_NAME"]]},
        {"Name": "vpc-id", "Values": [vpc_id]}
    ])["SecurityGroups"]

    if groups:
        sg_id = groups[0]["GroupId"]

        retry_on(
            {"DependencyViolation"},
            lambda: aws.ec2.delete_security_group(GroupId=sg_id),
            attempts=10,
            delay=15
        )

        print("Database security group deleted.")

    print("== Deleting the database password parameter ==")

    try:
        ssm.delete_parameter(
            Name=settings["DB_PASSWORD_PARAM"]
        )
    except ClientError as err:
        if error_code(err) != "ParameterNotFound":
            raise

    Path("db_outputs.env").unlink(missing_ok=True)

    print("Database removed.")


def main():
    settings = load_dotenv(".env")
    aws = AwsClients.create(settings["AWS_REGION"])
    rds = boto3.client("rds", region_name=settings["AWS_REGION"])
    ssm = boto3.client("ssm", region_name=settings["AWS_REGION"])

    delete_database(settings, aws, rds, ssm)


if __name__ == "__main__":
    main()

