import time
from pathlib import Path

from botocore.exceptions import ClientError

from stack.clients import AwsClients
from stack.config import load_dotenv
from stack.network import default_vpc_id
from stack.util import error_code


def ignore_missing(func, codes):
    try:
        return func()
    except ClientError as err:
        if error_code(err) not in codes:
            raise
        return None


def delete_asg(aws, name):
    groups = aws.autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[name]
    )["AutoScalingGroups"]

    if groups:
        if groups[0].get("Status") != "Delete in progress":
            aws.autoscaling.delete_auto_scaling_group(
                AutoScalingGroupName=name,
                ForceDelete=True
            )

    for attempt in range(60):
        remaining = aws.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[name]
        )["AutoScalingGroups"]

        if not remaining:
            print(f"{name} deleted.")
            return

        if attempt % 4 == 0:
            print(f"Waiting for {name} to finish deleting...")

        time.sleep(15)

    raise RuntimeError(
        f"Auto Scaling Group {name} was not deleted."
    )

def delete_load_balancer(aws, name):
    try:
        alb = aws.elbv2.describe_load_balancers(
            Names=[name]
        )["LoadBalancers"][0]
    except ClientError as err:
        if error_code(err) == "LoadBalancerNotFound":
            return
        raise

    arn = alb["LoadBalancerArn"]

    aws.elbv2.delete_load_balancer(
        LoadBalancerArn=arn
    )

    aws.elbv2.get_waiter("load_balancers_deleted").wait(
        LoadBalancerArns=[arn]
    )

def delete_target_group(aws, name):
    try:
        groups = aws.elbv2.describe_target_groups(
            Names=[name]
        )["TargetGroups"]
    except ClientError as err:
        if error_code(err) == "TargetGroupNotFound":
            print(f"{name} already deleted.")
            return
        raise

    arn = groups[0]["TargetGroupArn"]

    for attempt in range(30):
        try:
            aws.elbv2.delete_target_group(
                TargetGroupArn=arn
            )
            print(f"{name} deleted.")
            return

        except ClientError as err:
            code = error_code(err)

            if code == "TargetGroupNotFound":
                print(f"{name} already deleted.")
                return

            if code != "ResourceInUse":
                raise

            print(
                f"{name} still in use. "
                f"Retry {attempt + 1}/30..."
            )
            time.sleep(10)

    raise RuntimeError(
        f"Could not delete target group {name} after 30 attempts."
    )


def restore_security_groups(aws, settings):
    vpc_id = default_vpc_id(aws)

    groups = aws.ec2.describe_security_groups(Filters=[
        {"Name": "group-name", "Values": [settings["ALB_SG_NAME"]]},
        {"Name": "vpc-id", "Values": [vpc_id]}
    ])["SecurityGroups"]

    alb_sg = groups[0]["GroupId"] if groups else None
    app_sg = settings["APP_SECURITY_GROUP_ID"]

    if alb_sg:
        ignore_missing(
            lambda: aws.ec2.revoke_security_group_ingress(
                GroupId=app_sg,
                IpPermissions=[{
                    "IpProtocol": "tcp",
                    "FromPort": 3000,
                    "ToPort": 3000,
                    "UserIdGroupPairs": [{"GroupId": alb_sg}]
                }]
            ),
            {"InvalidPermission.NotFound"}
        )

    try:
        aws.ec2.authorize_security_group_ingress(
            GroupId=app_sg,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 3000,
                "ToPort": 3000,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
            }]
        )
    except ClientError as err:
        if error_code(err) != "InvalidPermission.Duplicate":
            raise

    if alb_sg:
        for attempt in range(10):
            try:
                aws.ec2.delete_security_group(GroupId=alb_sg)
                print("ALB security group deleted.")
                break
            except ClientError as err:
                if error_code(err) != "DependencyViolation":
                    raise
                if attempt == 9:
                    raise
                print("ALB network interfaces still releasing, waiting 15s...")
                time.sleep(15)


def delete_launch_template(aws, name):
    ignore_missing(
        lambda: aws.ec2.delete_launch_template(
            LaunchTemplateName=name
        ),
        {"InvalidLaunchTemplateName.NotFoundException"}
    )


def delete_role_and_profile(aws, role, profile):
    ignore_missing(
        lambda: aws.iam.remove_role_from_instance_profile(
            InstanceProfileName=profile,
            RoleName=role
        ),
        {"NoSuchEntity"}
    )

    ignore_missing(
        lambda: aws.iam.delete_instance_profile(
            InstanceProfileName=profile
        ),
        {"NoSuchEntity"}
    )

    ignore_missing(
        lambda: aws.iam.delete_role_policy(
            RoleName=role,
            PolicyName=f"{role}-policy"
        ),
        {"NoSuchEntity"}
    )

    ignore_missing(
        lambda: aws.iam.delete_role(
            RoleName=role
        ),
        {"NoSuchEntity"}
    )


def delete_weather_stack(settings, aws):
    print("== Deleting Auto Scaling Groups ==")

    delete_asg(aws, settings["WEATHER_ASG_NAME"])
    delete_asg(aws, settings["ADVISOR_ASG_NAME"])

    print("== Deleting the load balancer and target groups ==")

    delete_load_balancer(aws, settings["ALB_NAME"])

    delete_target_group(aws, settings["WEATHER_TG_NAME"])
    delete_target_group(aws, settings["ADVISOR_TG_NAME"])

    print("== Restoring the app security group and deleting the ALB security group ==")

    restore_security_groups(aws, settings)

    print("== Deleting launch templates ==")

    delete_launch_template(aws, settings["WEATHER_LT_NAME"])
    delete_launch_template(aws, settings["ADVISOR_LT_NAME"])

    print("== Removing IAM instance profiles and roles ==")

    delete_role_and_profile(
        aws,
        settings["WEATHER_ROLE_NAME"],
        settings["WEATHER_PROFILE_NAME"]
    )

    delete_role_and_profile(
        aws,
        settings["ADVISOR_ROLE_NAME"],
        settings["ADVISOR_PROFILE_NAME"]
    )

    Path("stack_outputs.env").unlink(missing_ok=True)

    print("Weather stack removed.")
    print("The Gemini key parameter and database were left in place.")


def main():
    settings = load_dotenv(".env")
    aws = AwsClients.create(settings["AWS_REGION"])
    delete_weather_stack(settings, aws)


if __name__ == "__main__":
    main()
