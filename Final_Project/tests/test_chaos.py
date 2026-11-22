"""Opt-in real EC2 replacement test. Run explicitly with -m chaos."""
import os
import time
import boto3
import requests
import pytest


@pytest.mark.chaos
def test_asg_recovers_after_instance_termination():
    region = os.environ['AWS_REGION']
    asg_name = os.environ['WEATHER_ASG_NAME']
    weather_url = os.environ['WEATHER_URL']
    max_seconds = int(os.getenv('RECOVERY_SLO_SECONDS', '300'))
    asg = boto3.client('autoscaling', region_name=region)
    ec2 = boto3.client('ec2', region_name=region)
    groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])['AutoScalingGroups']
    assert groups and groups[0]['Instances']
    instance = groups[0]['Instances'][0]['InstanceId']
    ec2.terminate_instances(InstanceIds=[instance])
    start = time.monotonic()
    while time.monotonic() - start <= max_seconds:
        try:
            groups = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])['AutoScalingGroups']
            replaced = groups and any(x['InstanceId'] != instance and x['HealthStatus'] == 'Healthy'
                                      for x in groups[0]['Instances'])
            if replaced and requests.get(weather_url, timeout=5).status_code == 200:
                elapsed = time.monotonic() - start
                print(f"\nRecovery check passed in {elapsed:.2f} seconds")
                return
        except requests.RequestException:
            pass
        time.sleep(10)
    pytest.fail('Weather tier did not recover within its SLO')
