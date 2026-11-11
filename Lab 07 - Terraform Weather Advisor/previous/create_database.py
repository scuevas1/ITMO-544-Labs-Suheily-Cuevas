import boto3
import secrets
from pathlib import Path
from botocore.exceptions import ClientError

from stack.clients import AwsClients
from stack.config import load_dotenv
from stack.network import default_vpc_id, subnet_in_az
from stack.util import error_code


def create_database(settings, aws, rds, ssm):
    """Create the PostgreSQL database and supporting AWS resources."""
    print("== 1. Default VPC and subnets in both AZs ==")

    vpc_id = default_vpc_id(aws)
    subnet_a = subnet_in_az(aws, vpc_id, settings["AZ_A"])
    subnet_b = subnet_in_az(aws, vpc_id, settings["AZ_B"])
    db_port = int(settings["DB_PORT"])

    print("== 2. Database security group ==")

    groups = aws.ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [settings["DB_SG_NAME"]]},
        {"Name": "vpc-id", "Values": [vpc_id]}
    ])["SecurityGroups"]

    if groups:
        sg_id = groups[0]["GroupId"]
        print("Database security group already exists, skipping.")
    else:
        sg_id = aws.ec2.create_security_group(
            GroupName=settings["DB_SG_NAME"],
            Description="PostgreSQL access from the lab app instances only",
            VpcId=vpc_id
        )["GroupId"]

    try:
        aws.ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": db_port,
                "ToPort": db_port,
                "UserIdGroupPairs": [{
                    "GroupId": settings["APP_SECURITY_GROUP_ID"]
                }]
            }]
        )
    except ClientError as err:
        if error_code(err) != "InvalidPermission.Duplicate":
            raise

    print("== 3. DB subnet group ==")

    try:
        rds.create_db_subnet_group(
            DBSubnetGroupName=settings["DB_SUBNET_GROUP_NAME"],
            DBSubnetGroupDescription="Lab subnets for the weather database",
            SubnetIds=[subnet_a, subnet_b]
        )
    except ClientError as err:
        if error_code(err) not in (
            "DBSubnetGroupAlreadyExists",
            "DBSubnetGroupAlreadyExistsFault"
        ):
            raise

    print("== 4. Database password ==")

    try:
        password = ssm.get_parameter(
            Name=settings["DB_PASSWORD_PARAM"],
            WithDecryption=True
        )["Parameter"]["Value"]
        print("Password parameter already exists, keeping it.")
    except ClientError as err:
        if error_code(err) != "ParameterNotFound":
            raise

        password = secrets.token_hex(16)

        ssm.put_parameter(
            Name=settings["DB_PASSWORD_PARAM"],
            Type="SecureString",
            Value=password
        )

    print("== 5. PostgreSQL instance ==")

    try:
        rds.describe_db_instances(
            DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
        )
        print("Database already exists, skipping.")
    except ClientError as err:
        if error_code(err) not in (
            "DBInstanceNotFound",
            "DBInstanceNotFoundFault"
        ):
            raise

        rds.create_db_instance(
            DBInstanceIdentifier=settings["DB_INSTANCE_ID"],
            DBInstanceClass=settings["DB_INSTANCE_CLASS"],
            Engine="postgres",
            AllocatedStorage=20,
            StorageType="gp2",
            MasterUsername=settings["DB_USER"],
            MasterUserPassword=password,
            DBName=settings["DB_NAME"],
            DBSubnetGroupName=settings["DB_SUBNET_GROUP_NAME"],
            VpcSecurityGroupIds=[sg_id],
            AvailabilityZone=settings["AZ_A"],
            BackupRetentionPeriod=0,
            MultiAZ=False,
            PubliclyAccessible=False,
            AutoMinorVersionUpgrade=False,
            DeletionProtection=False,
            StorageEncrypted=True
        )

    del password

    print("Waiting for the database to become available...")

    rds.get_waiter("db_instance_available").wait(
        DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
    )

    db = rds.describe_db_instances(
        DBInstanceIdentifier=settings["DB_INSTANCE_ID"]
    )["DBInstances"][0]

    db_host = db["Endpoint"]["Address"]

    Path("db_outputs.env").write_text(
        f"DB_HOST={db_host}\n"
        f"DB_SECURITY_GROUP_ID={sg_id}\n"
    )

    print(f"Done. Database endpoint: {db_host}")
    print("Automated backups are OFF (retention 0).")


def main():
    """Load configuration and initialize the AWS clients."""
    settings = load_dotenv(".env")
    aws = AwsClients.create(settings["AWS_REGION"])

    rds = boto3.client(
        "rds",
        region_name=settings["AWS_REGION"]
    )

    ssm = boto3.client(
        "ssm",
        region_name=settings["AWS_REGION"]
    )

    create_database(settings, aws, rds, ssm)


if __name__ == "__main__":
    main()
