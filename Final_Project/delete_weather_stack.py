import argparse
import time
from pathlib import Path
from botocore.exceptions import ClientError
from stack.config import settings
from stack.aws import clients, code, ignore_missing


def wait_gone(check,label,attempts=60,interval=5):
    for _ in range(attempts):
        if not check():return
        time.sleep(interval)
    raise RuntimeError('Deletion timeout: '+label)


def delete_asg(aws,name):
    client=aws['asg']
    exists=lambda:bool(client.describe_auto_scaling_groups(AutoScalingGroupNames=[name])['AutoScalingGroups'])
    if exists():
        try:client.delete_auto_scaling_group(AutoScalingGroupName=name,ForceDelete=True)
        except ClientError as e:
            if code(e)!='ResourceInUse':raise
        wait_gone(exists,name)


def lb_arn(aws,name):
    try:return aws['elbv2'].describe_load_balancers(Names=[name])['LoadBalancers'][0]['LoadBalancerArn']
    except ClientError as e:
        if code(e)=='LoadBalancerNotFound':return None
        raise


def tg_arn(aws,name):
    try:return aws['elbv2'].describe_target_groups(Names=[name])['TargetGroups'][0]['TargetGroupArn']
    except ClientError as e:
        if code(e)=='TargetGroupNotFound':return None
        raise


def delete_lb(aws,name):
    arn=lb_arn(aws,name)
    if arn:
        aws['elbv2'].delete_load_balancer(LoadBalancerArn=arn)
        wait_gone(lambda:lb_arn(aws,name),name)


def delete_tg(aws,name):
    arn=tg_arn(aws,name)
    if not arn:return
    for n in range(30):
        try:
            aws['elbv2'].delete_target_group(TargetGroupArn=arn)
            break
        except ClientError as e:
            if code(e)=='TargetGroupNotFound':return
            if code(e)!='ResourceInUse' or n==29:raise
            time.sleep(5)
    wait_gone(lambda:tg_arn(aws,name),name)


def delete_launch_template(aws,name):
    ignore_missing(lambda:aws['ec2'].delete_launch_template(LaunchTemplateName=name),'InvalidLaunchTemplateName.NotFoundException')


def delete_security_group(aws,cfg):
    ec2=aws['ec2']
    app=ec2.describe_security_groups(GroupIds=[cfg['APP_SECURITY_GROUP_ID']])['SecurityGroups'][0]
    groups=ec2.describe_security_groups(Filters=[{'Name':'group-name','Values':[cfg['ALB_SG_NAME']]},{'Name':'vpc-id','Values':[app['VpcId']]}])['SecurityGroups']
    if not groups:return
    group_id=groups[0]['GroupId']
    if group_id==cfg['APP_SECURITY_GROUP_ID']:raise RuntimeError('Refusing to delete shared SG')
    for rule in app.get('IpPermissions',[]):
        if rule.get('IpProtocol')!='tcp' or rule.get('FromPort')!=3000 or rule.get('ToPort')!=3000:continue
        matches=[r for r in rule.get('UserIdGroupPairs',[]) if r['GroupId']==group_id]
        if matches:
            ignore_missing(lambda:ec2.revoke_security_group_ingress(GroupId=cfg['APP_SECURITY_GROUP_ID'],IpPermissions=[{'IpProtocol':'tcp','FromPort':3000,'ToPort':3000,'UserIdGroupPairs':matches}]),'InvalidPermission.NotFound')
    for attempt in range(30):
        try:
            ec2.delete_security_group(GroupId=group_id)
            return
        except ClientError as e:
            if code(e)=='InvalidGroup.NotFound':return
            if code(e)!='DependencyViolation' or attempt==29:raise
            time.sleep(5)


def delete_role(aws,role,profile):
    iam=aws['iam']
    try:
        obj=iam.get_instance_profile(InstanceProfileName=profile)['InstanceProfile']
        for r in obj['Roles']:
            if r['RoleName']!=role:raise RuntimeError('Unexpected profile member')
            iam.remove_role_from_instance_profile(InstanceProfileName=profile,RoleName=role)
        iam.delete_instance_profile(InstanceProfileName=profile)
    except ClientError as e:
        if code(e)!='NoSuchEntity':raise
    try:
        for page in iam.get_paginator('list_role_policies').paginate(RoleName=role):
            for name in page['PolicyNames']:iam.delete_role_policy(RoleName=role,PolicyName=name)
        for page in iam.get_paginator('list_attached_role_policies').paginate(RoleName=role):
            for attachment in page['AttachedPolicies']:iam.detach_role_policy(RoleName=role,PolicyArn=attachment['PolicyArn'])
        iam.delete_role(RoleName=role)
    except ClientError as e:
        if code(e)!='NoSuchEntity':raise


def delete_table(aws,name):
    db=aws['dynamodb']
    def exists():
        try:db.describe_table(TableName=name);return True
        except ClientError as e:
            if code(e)=='ResourceNotFoundException':return False
            raise
    if exists():
        ignore_missing(lambda:db.delete_table(TableName=name),'ResourceNotFoundException')
        wait_gone(exists,name)


def delete_topic(aws,name):
    """Remove only this project's topic, including its SNS subscriptions."""
    account=aws['sts'].get_caller_identity()['Account']
    region=aws['sns'].meta.region_name
    arn=f'arn:aws:sns:{region}:{account}:{name}'
    aws['sns'].delete_topic(TopicArn=arn)


def cleanup(cfg,aws):
    actions=[]
    for tier in ('WEATHER','ADVISOR'):actions.append(('ASG '+tier,lambda tier=tier:delete_asg(aws,cfg[tier+'_ASG_NAME'])))
    actions.append(('ALB',lambda:delete_lb(aws,cfg['ALB_NAME'])))
    for tier in ('WEATHER','ADVISOR'):actions.append(('Target group '+tier,lambda tier=tier:delete_tg(aws,cfg[tier+'_TG_NAME'])))
    for tier in ('WEATHER','ADVISOR'):actions.append(('Launch template '+tier,lambda tier=tier:delete_launch_template(aws,cfg[tier+'_LT_NAME'])))
    actions.append(('ALB SG',lambda:delete_security_group(aws,cfg)))
    for tier in ('WEATHER','ADVISOR'):actions.append(('IAM '+tier,lambda tier=tier:delete_role(aws,cfg[tier+'_ROLE_NAME'],cfg[tier+'_PROFILE_NAME'])))
    for key in ('FACTS_TABLE_NAME','REPORT_TABLE_NAME','COUNTER_TABLE_NAME'):actions.append(('Table '+key,lambda key=key:delete_table(aws,cfg[key])))
    actions.append(('SNS topic',lambda:delete_topic(aws,cfg['SNS_TOPIC_NAME'])))
    actions.append(('Gemini SSM parameter', lambda:ignore_missing(
        lambda:aws['ssm'].delete_parameter(Name=cfg['GEMINI_KEY_PARAM']),
        'ParameterNotFound')))
    failed=[]
    for label,action in actions:
        print('Deleting:',label)
        try:action()
        except Exception as exc:
            print('FAILED:',label,type(exc).__name__,str(exc));failed.append(label)
    if failed:raise RuntimeError('Cleanup incomplete: '+', '.join(failed))
    Path('stack_outputs.json').unlink(missing_ok=True)
    print('Final-project resources removed; shared app security group preserved.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='.env')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--confirm',default='')
    args=parser.parse_args()
    cfg=settings(args.config)
    if not args.execute:
        print('PREVIEW ONLY. Project resources:')
        for k in cfg:
            if k.endswith(('_NAME','_TABLE_NAME')):print(k,cfg[k])
        return
    if args.confirm!='DELETE-FINAL-PROJECT':raise RuntimeError('Pass --execute --confirm DELETE-FINAL-PROJECT')
    cleanup(cfg,clients(cfg['AWS_REGION']))

if __name__=='__main__':main()
