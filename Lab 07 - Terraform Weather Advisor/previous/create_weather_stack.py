import base64
import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from stack.clients import AwsClients
from stack.config import load_dotenv
from stack.network import default_vpc_id, subnet_in_az
from stack.util import error_code


def ensure_role_and_profile(aws, role, profile, secret_arn):
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }

    try:
        aws.iam.create_role(
            RoleName=role,
            AssumeRolePolicyDocument=json.dumps(trust)
        )
    except ClientError as err:
        if error_code(err) != "EntityAlreadyExists":
            raise

    try:
        aws.iam.create_instance_profile(
            InstanceProfileName=profile
        )
    except ClientError as err:
        if error_code(err) != "EntityAlreadyExists":
            raise

    profile_data = aws.iam.get_instance_profile(
        InstanceProfileName=profile
    )["InstanceProfile"]

    roles = [
        item["RoleName"]
        for item in profile_data["Roles"]
    ]

    if role not in roles:
        aws.iam.add_role_to_instance_profile(
            InstanceProfileName=profile,
            RoleName=role
        )

    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["ssm:GetParameter"],
            "Resource": secret_arn
        }]
    }

    aws.iam.put_role_policy(
        RoleName=role,
        PolicyName=f"{role}-policy",
        PolicyDocument=json.dumps(policy)
    )

    if role == "itmo-444-544-weather-role":
        policy["Statement"].append({
            "Effect": "Deny",
            "Action": "ssm:GetParameter",
            "Resource": secret_arn.replace(
                "/db-password", "/gemini-api-key"
            )
        })


def ensure_security_groups(aws, settings, vpc_id):
    groups = aws.ec2.describe_security_groups(Filters=[
        {
            "Name": "group-name",
            "Values": [settings["ALB_SG_NAME"]]
        },
        {
            "Name": "vpc-id",
            "Values": [vpc_id]
        }
    ])["SecurityGroups"]

    if groups:
        alb_sg = groups[0]["GroupId"]
        print("ALB security group already exists, skipping.")
    else:
        alb_sg = aws.ec2.create_security_group(
            GroupName=settings["ALB_SG_NAME"],
            Description="Allow inbound to the ALB on app listener ports",
            VpcId=vpc_id
        )["GroupId"]

    for key in ("WEATHER_LISTENER_PORT", "ADVISOR_LISTENER_PORT"):
        port = int(settings[key])

        try:
            aws.ec2.authorize_security_group_ingress(
                GroupId=alb_sg,
                IpPermissions=[{
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "IpRanges": [{
                        "CidrIp": "0.0.0.0/0"
                    }]
                }]
            )
        except ClientError as err:
            if error_code(err) != "InvalidPermission.Duplicate":
                raise

    app_sg = settings["APP_SECURITY_GROUP_ID"]

    existing_rules = aws.ec2.describe_security_groups(
        GroupIds=[app_sg]
    )["SecurityGroups"][0].get("IpPermissions", [])

    for rule in existing_rules:
        protocol = rule.get("IpProtocol")
        low = rule.get("FromPort", 0)
        high = rule.get("ToPort", 65535)
        covers_app_port = protocol == "-1" or (
            protocol == "tcp" and low <= 3000 <= high
        )
        if not covers_app_port:
            continue

        ipv4 = [x for x in rule.get("IpRanges", [])
                if x.get("CidrIp") == "0.0.0.0/0"]
        ipv6 = [x for x in rule.get("Ipv6Ranges", [])
                if x.get("CidrIpv6") == "::/0"]
        if ipv4 or ipv6:
            permission = {
                "IpProtocol": protocol,
                "FromPort": low,
                "ToPort": high,
            }
            if ipv4:
                permission["IpRanges"] = ipv4
            if ipv6:
                permission["Ipv6Ranges"] = ipv6
            aws.ec2.revoke_security_group_ingress(
                GroupId=app_sg, IpPermissions=[permission]
            )

    try:
        aws.ec2.authorize_security_group_ingress(
            GroupId=app_sg,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 3000,
                "ToPort": 3000,
                "UserIdGroupPairs": [{
                    "GroupId": alb_sg
                }]
            }]
        )
    except ClientError as err:
        if error_code(err) != "InvalidPermission.Duplicate":
            raise

    return alb_sg


def ensure_target_group(aws, name, vpc_id):
    try:
        groups = aws.elbv2.describe_target_groups(
            Names=[name]
        )["TargetGroups"]

        print(f"Target group {name} already exists, skipping.")
        return groups[0]["TargetGroupArn"]

    except ClientError as err:
        if error_code(err) != "TargetGroupNotFound":
            raise

    response = aws.elbv2.create_target_group(
        Name=name,
        Protocol="HTTP",
        Port=3000,
        VpcId=vpc_id,
        TargetType="instance",
        HealthCheckProtocol="HTTP",
        HealthCheckPath="/",
        HealthCheckIntervalSeconds=10,
        HealthCheckTimeoutSeconds=5,
        HealthyThresholdCount=2,
        UnhealthyThresholdCount=2
    )

    return response["TargetGroups"][0]["TargetGroupArn"]


def ensure_load_balancer(aws, settings, subnets, alb_sg):
    try:
        alb = aws.elbv2.describe_load_balancers(
            Names=[settings["ALB_NAME"]]
        )["LoadBalancers"][0]

        print("Load balancer already exists, skipping.")

    except ClientError as err:
        if error_code(err) != "LoadBalancerNotFound":
            raise

        alb = aws.elbv2.create_load_balancer(
            Name=settings["ALB_NAME"],
            Subnets=subnets,
            SecurityGroups=[alb_sg],
            Scheme="internet-facing",
            Type="application"
        )["LoadBalancers"][0]

    arn = alb["LoadBalancerArn"]

    print("Waiting for the ALB to become active...")

    aws.elbv2.get_waiter("load_balancer_available").wait(
        LoadBalancerArns=[arn]
    )

    alb = aws.elbv2.describe_load_balancers(
        LoadBalancerArns=[arn]
    )["LoadBalancers"][0]

    return arn, alb["DNSName"]


def ensure_listener(aws, alb_arn, port, tg_arn):
    listeners = aws.elbv2.describe_listeners(
        LoadBalancerArn=alb_arn
    )["Listeners"]

    for listener in listeners:
        if listener["Port"] != port:
            continue
        actions = listener.get("DefaultActions", [])
        if any(action.get("TargetGroupArn") == tg_arn for action in actions):
            print(f"Listener on port {port} already exists, skipping.")
            return
        aws.elbv2.modify_listener(
            ListenerArn=listener["ListenerArn"],
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}]
        )
        print(f"Listener on port {port} updated.")
        return

    aws.elbv2.create_listener(
        LoadBalancerArn=alb_arn,
        Protocol="HTTP",
        Port=port,
        DefaultActions=[{
            "Type": "forward",
            "TargetGroupArn": tg_arn
        }]
    )


def build_user_data(name, app_dir, region, extra_env, extra_setup=""):
    app_js = base64.b64encode(
        (Path(app_dir) / "app.js").read_bytes()
    ).decode()

    package_json = base64.b64encode(
        (Path(app_dir) / "package.json").read_bytes()
    ).decode()

    return f"""#!/bin/bash
set -e
dnf update -y
dnf install -y nodejs
mkdir -p /opt/app
{extra_setup}
echo "{app_js}" | base64 -d > /opt/app/app.js
echo "{package_json}" | base64 -d > /opt/app/package.json
cd /opt/app
npm install --omit=dev
cat > /etc/systemd/system/{name}.service << 'SERVICE'
[Unit]
Description={name} app
After=network.target
[Service]
Environment=PORT=3000
Environment=AWS_REGION={region}
{extra_env}
WorkingDirectory=/opt/app
ExecStart=/usr/bin/node /opt/app/app.js
Restart=always
User=ec2-user
[Install]
WantedBy=multi-user.target
SERVICE
chown -R ec2-user:ec2-user /opt/app
systemctl daemon-reload
systemctl enable {name}.service
systemctl start {name}.service
"""


def ensure_launch_template(aws, settings, name, profile, user_data, tag):
    if len(user_data.encode()) > 16384:
        raise ValueError(f"{name} user-data exceeds 16 KB")

    data = {
        "ImageId": settings["AMI_ID"],
        "InstanceType": settings["INSTANCE_TYPE"],
        "KeyName": settings["KEY_NAME"],
        "SecurityGroupIds": [
            settings["APP_SECURITY_GROUP_ID"]
        ],
        "IamInstanceProfile": {
            "Name": profile
        },
        "UserData": base64.b64encode(
            user_data.encode()
        ).decode(),
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [{
                "Key": "Name",
                "Value": tag
            }]
        }]
    }

    try:
        aws.ec2.describe_launch_templates(
            LaunchTemplateNames=[name]
        )
    except ClientError as err:
        if error_code(err) != "InvalidLaunchTemplateName.NotFoundException":
            raise

        aws.ec2.create_launch_template(
            LaunchTemplateName=name,
            LaunchTemplateData=data
        )

        print(f"Launch template {name} created.")
        return

    versions = aws.ec2.describe_launch_template_versions(
        LaunchTemplateName=name,
        Versions=["$Latest"]
    )["LaunchTemplateVersions"]

    existing = versions[0]["LaunchTemplateData"]

    keys = (
        "ImageId",
        "InstanceType",
        "KeyName",
        "SecurityGroupIds",
        "IamInstanceProfile",
        "UserData",
        "TagSpecifications"
    )

    unchanged = all(
        existing.get(key) == data.get(key)
        for key in keys
    )

    if unchanged:
        print(f"Launch template {name} unchanged, skipping.")
        return

    response = aws.ec2.create_launch_template_version(
        LaunchTemplateName=name,
        SourceVersion="$Latest",
        LaunchTemplateData=data
    )

    version = response["LaunchTemplateVersion"]["VersionNumber"]

    aws.ec2.modify_launch_template(
        LaunchTemplateName=name,
        DefaultVersion=str(version)
    )

    print(f"Launch template {name} updated to version {version}.")


def ensure_asg(aws, name, lt_name, tg_arn, subnets, tag):
    groups = aws.autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[name]
    )["AutoScalingGroups"]

    if groups:
        print(f"Auto Scaling Group {name} already exists, skipping."
              " Existing instances are not automatically replaced.")
        return

    aws.autoscaling.create_auto_scaling_group(
        AutoScalingGroupName=name,
        LaunchTemplate={
            "LaunchTemplateName": lt_name,
            "Version": "$Latest"
        },
        MinSize=1,
        MaxSize=1,
        DesiredCapacity=1,
        VPCZoneIdentifier=",".join(subnets),
        TargetGroupARNs=[tg_arn],
        HealthCheckType="ELB",
        HealthCheckGracePeriod=120,
        Tags=[{
            "ResourceId": name,
            "ResourceType": "auto-scaling-group",
            "Key": "Name",
            "Value": tag,
            "PropagateAtLaunch": True
        }]
    )


def create_weather_stack(settings, aws, ssm, sts):
    print("== 1. Checking the Gemini key and the database ==")

    try:
        ssm.get_parameter(
            Name=settings["GEMINI_PARAM_NAME"]
        )
    except ClientError as err:
        if error_code(err) == "ParameterNotFound":
            raise RuntimeError(
                "Gemini parameter not found. Complete Part C first."
            ) from err
        raise

    if not Path("db_outputs.env").exists():
        raise RuntimeError(
            "db_outputs.env not found. Run create_database.py first."
        )

    db_outputs = load_dotenv("db_outputs.env")
    db_host = db_outputs["DB_HOST"]

    account = sts.get_caller_identity()["Account"]
    region = settings["AWS_REGION"]

    gemini_arn = (
        f"arn:aws:ssm:{region}:{account}:parameter"
        f"{settings['GEMINI_PARAM_NAME']}"
    )

    db_password_arn = (
        f"arn:aws:ssm:{region}:{account}:parameter"
        f"{settings['DB_PASSWORD_PARAM']}"
    )

    print("== 2. IAM roles and instance profiles ==")

    ensure_role_and_profile(
        aws,
        settings["WEATHER_ROLE_NAME"],
        settings["WEATHER_PROFILE_NAME"],
        db_password_arn
    )

    ensure_role_and_profile(
        aws,
        settings["ADVISOR_ROLE_NAME"],
        settings["ADVISOR_PROFILE_NAME"],
        gemini_arn
    )

    print("Waiting 15s for IAM propagation...")
    time.sleep(15)

    print("== 3. Default VPC and subnets in both AZs ==")

    vpc_id = default_vpc_id(aws)

    subnet_a = subnet_in_az(
        aws, vpc_id, settings["AZ_A"]
    )

    subnet_b = subnet_in_az(
        aws, vpc_id, settings["AZ_B"]
    )

    subnets = [subnet_a, subnet_b]

    print("== 4. Security groups ==")

    alb_sg = ensure_security_groups(
        aws, settings, vpc_id
    )

    print("== 5. Target groups and the load balancer ==")

    weather_tg = ensure_target_group(
        aws,
        settings["WEATHER_TG_NAME"],
        vpc_id
    )

    advisor_tg = ensure_target_group(
        aws,
        settings["ADVISOR_TG_NAME"],
        vpc_id
    )

    alb_arn, alb_dns = ensure_load_balancer(
        aws, settings, subnets, alb_sg
    )

    ensure_listener(
        aws,
        alb_arn,
        int(settings["WEATHER_LISTENER_PORT"]),
        weather_tg
    )

    ensure_listener(
        aws,
        alb_arn,
        int(settings["ADVISOR_LISTENER_PORT"]),
        advisor_tg
    )

    print("== 6. Launch templates ==")

    weather_env = "\n".join([
        f'Environment="NWS_USER_AGENT=(itmo-444-544 weather lab, {settings["CONTACT_EMAIL"]})"',
        f"Environment=DB_HOST={db_host}",
        f"Environment=DB_NAME={settings['DB_NAME']}",
        f"Environment=DB_USER={settings['DB_USER']}",
        f"Environment=DB_PASSWORD_PARAM={settings['DB_PASSWORD_PARAM']}",
        f"Environment=CACHE_SECONDS={settings['CACHE_SECONDS']}"
    ])

    weather_setup = (
        "dnf install -y postgresql15\n"
        "curl -fsS -o /opt/app/rds-ca.pem "
        "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
    )

    advisor_env = "\n".join([
        f"Environment=WEATHER_URL=http://{alb_dns}:{settings['WEATHER_LISTENER_PORT']}",
        f"Environment=GEMINI_KEY_PARAM={settings['GEMINI_PARAM_NAME']}",
        f"Environment=GEMINI_MODEL={settings['GEMINI_MODEL']}",
        f"Environment=KEY_CACHE_SECONDS={settings['KEY_CACHE_SECONDS']}"
    ])

    weather_data = build_user_data(
        "weather",
        "weather-app",
        region,
        weather_env,
        weather_setup
    )

    advisor_data = build_user_data(
        "advisor",
        "advisor-app",
        region,
        advisor_env
    )

    ensure_launch_template(
        aws,
        settings,
        settings["WEATHER_LT_NAME"],
        settings["WEATHER_PROFILE_NAME"],
        weather_data,
        "weather-app"
    )

    ensure_launch_template(
        aws,
        settings,
        settings["ADVISOR_LT_NAME"],
        settings["ADVISOR_PROFILE_NAME"],
        advisor_data,
        "advisor-app"
    )

    print("== 7. Auto Scaling Groups ==")

    ensure_asg(
        aws,
        settings["WEATHER_ASG_NAME"],
        settings["WEATHER_LT_NAME"],
        weather_tg,
        subnets,
        "weather-app"
    )

    ensure_asg(
        aws,
        settings["ADVISOR_ASG_NAME"],
        settings["ADVISOR_LT_NAME"],
        advisor_tg,
        subnets,
        "advisor-app"
    )

    Path("stack_outputs.env").write_text(
        f"VPC_ID={vpc_id}\n"
        f"SUBNET_A={subnet_a}\n"
        f"SUBNET_B={subnet_b}\n"
        f"ALB_SECURITY_GROUP_ID={alb_sg}\n"
        f"ALB_ARN={alb_arn}\n"
        f"ALB_DNS_NAME={alb_dns}\n"
        f"WEATHER_TG_ARN={weather_tg}\n"
        f"ADVISOR_TG_ARN={advisor_tg}\n"
    )

    print()
    print(f"Done. ALB DNS name: {alb_dns}")

    print(
        f"Weather service: http://{alb_dns}:"
        f"{settings['WEATHER_LISTENER_PORT']}/weather?zip=60616"
    )

    print(
        f"Advisor page: http://{alb_dns}:"
        f"{settings['ADVISOR_LISTENER_PORT']}/"
    )

    print("Give the target groups 2 to 3 minutes to report healthy.")


def main():
    settings = load_dotenv(".env")
    required = (
        "AWS_REGION", "AZ_A", "AZ_B", "AMI_ID", "INSTANCE_TYPE",
        "KEY_NAME", "APP_SECURITY_GROUP_ID", "GEMINI_PARAM_NAME",
        "DB_PASSWORD_PARAM", "GEMINI_MODEL", "CONTACT_EMAIL"
    )
    missing = [key for key in required if not settings.get(key)]
    if missing:
        raise RuntimeError("Missing .env settings: " + ", ".join(missing))
    aws = AwsClients.create(settings["AWS_REGION"])

    session = boto3.session.Session(
        region_name=settings["AWS_REGION"]
    )

    create_weather_stack(
        settings,
        aws,
        session.client("ssm"),
        session.client("sts")
    )


if __name__ == "__main__":
    main()
