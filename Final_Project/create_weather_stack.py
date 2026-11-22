import argparse
import base64
import json
import time
from pathlib import Path
from botocore.exceptions import ClientError
from stack.config import settings
from stack.aws import clients, code, ensure_table, ensure_role, role_policy, ensure_topic
from stack.boot import build_user_data


def ensure_alb_sg(aws,cfg,vpc):
    ec2=aws['ec2']
    groups=ec2.describe_security_groups(Filters=[{'Name':'group-name','Values':[cfg['ALB_SG_NAME']]},{'Name':'vpc-id','Values':[vpc]}])['SecurityGroups']
    gid=groups[0]['GroupId'] if groups else ec2.create_security_group(GroupName=cfg['ALB_SG_NAME'],Description='Final project ALB',VpcId=vpc)['GroupId']
    for label in ('WEATHER','ADVISOR'):
        try:ec2.authorize_security_group_ingress(GroupId=gid,IpPermissions=[{'IpProtocol':'tcp','FromPort':int(cfg[label+'_LISTENER_PORT']),'ToPort':int(cfg[label+'_LISTENER_PORT']),'IpRanges':[{'CidrIp':'0.0.0.0/0'}]}])
        except ClientError as e:
            if code(e)!='InvalidPermission.Duplicate':raise
    app_group=ec2.describe_security_groups(GroupIds=[cfg['APP_SECURITY_GROUP_ID']])['SecurityGroups'][0]
    if app_group['VpcId']!=vpc:raise RuntimeError('App security group is in another VPC')
    for rule in app_group.get('IpPermissions',[]):
        covers=rule['IpProtocol']=='-1' or rule['IpProtocol']=='tcp' and rule.get('FromPort',65536)<=3000<=rule.get('ToPort',-1)
        if covers and (rule.get('IpRanges') or rule.get('Ipv6Ranges')):
            raise RuntimeError('Shared app SG exposes port 3000 publicly; remove that rule before deployment')
    try:ec2.authorize_security_group_ingress(GroupId=cfg['APP_SECURITY_GROUP_ID'],IpPermissions=[{'IpProtocol':'tcp','FromPort':3000,'ToPort':3000,'UserIdGroupPairs':[{'GroupId':gid}]}])
    except ClientError as e:
        if code(e)!='InvalidPermission.Duplicate':raise
    return gid


def ensure_target(aws,name,vpc):
    client=aws['elbv2']
    try:return client.describe_target_groups(Names=[name])['TargetGroups'][0]['TargetGroupArn']
    except ClientError as e:
        if code(e)!='TargetGroupNotFound':raise
    return client.create_target_group(Name=name,Protocol='HTTP',Port=3000,VpcId=vpc,TargetType='instance',HealthCheckPath='/',HealthCheckIntervalSeconds=15,HealthCheckTimeoutSeconds=5,HealthyThresholdCount=2,UnhealthyThresholdCount=2)['TargetGroups'][0]['TargetGroupArn']


def ensure_alb(aws,cfg,subnets,sg):
    lb=aws['elbv2']
    try:existing=lb.describe_load_balancers(Names=[cfg['ALB_NAME']])['LoadBalancers'][0]
    except ClientError as e:
        if code(e)!='LoadBalancerNotFound':raise
        existing=lb.create_load_balancer(Name=cfg['ALB_NAME'],Subnets=subnets,SecurityGroups=[sg],Scheme='internet-facing',Type='application')['LoadBalancers'][0]
    arn=existing['LoadBalancerArn']
    lb.get_waiter('load_balancer_available').wait(LoadBalancerArns=[arn])
    obj=lb.describe_load_balancers(LoadBalancerArns=[arn])['LoadBalancers'][0]
    return arn,obj['DNSName']


def ensure_listener(lb,arn,port,target):
    for item in lb.describe_listeners(LoadBalancerArn=arn)['Listeners']:
        if item['Port']==port:
            if not any(a.get('TargetGroupArn')==target for a in item.get('DefaultActions',[])):
                lb.modify_listener(ListenerArn=item['ListenerArn'],DefaultActions=[{'Type':'forward','TargetGroupArn':target}])
            return
    lb.create_listener(LoadBalancerArn=arn,Protocol='HTTP',Port=port,DefaultActions=[{'Type':'forward','TargetGroupArn':target}])


def ensure_template(aws,cfg,tier,user_data):
    ec2=aws['ec2']
    name=cfg[tier.upper()+'_LT_NAME']
    data={'ImageId':cfg['AMI_ID'],'InstanceType':cfg['INSTANCE_TYPE'],'SecurityGroupIds':[cfg['APP_SECURITY_GROUP_ID']],'IamInstanceProfile':{'Name':cfg[tier.upper()+'_PROFILE_NAME']},'UserData':base64.b64encode(user_data.encode()).decode(),'TagSpecifications':[{'ResourceType':'instance','Tags':[{'Key':'Project','Value':'itmo-544-final'},{'Key':'Name','Value':f'itmo-544-final-{tier}'}]}]}
    if cfg.get('KEY_NAME'):data['KeyName']=cfg['KEY_NAME']
    try:
        ec2.describe_launch_templates(LaunchTemplateNames=[name])
    except ClientError as e:
        if code(e)!='InvalidLaunchTemplateName.NotFoundException':raise
        ec2.create_launch_template(LaunchTemplateName=name,LaunchTemplateData=data)
        return
    last=ec2.describe_launch_template_versions(LaunchTemplateName=name,Versions=['$Latest'])['LaunchTemplateVersions'][0]['LaunchTemplateData']
    if all(last.get(key)==value for key,value in data.items()):return
    v=ec2.create_launch_template_version(LaunchTemplateName=name,SourceVersion='$Latest',LaunchTemplateData=data)['LaunchTemplateVersion']['VersionNumber']
    ec2.modify_launch_template(LaunchTemplateName=name,DefaultVersion=str(v))


def ensure_asg(aws,cfg,tier,target,subnets):
    asg=aws['asg']
    name=cfg[tier.upper()+'_ASG_NAME']
    if asg.describe_auto_scaling_groups(AutoScalingGroupNames=[name])['AutoScalingGroups']:
        print('Existing ASG: '+name+' (instances not automatically replaced)')
        return
    asg.create_auto_scaling_group(AutoScalingGroupName=name,LaunchTemplate={'LaunchTemplateName':cfg[tier.upper()+'_LT_NAME'],'Version':'$Default'},MinSize=1,MaxSize=1,DesiredCapacity=1,VPCZoneIdentifier=','.join(subnets),TargetGroupARNs=[target],HealthCheckType='ELB',HealthCheckGracePeriod=180,Tags=[{'ResourceId':name,'ResourceType':'auto-scaling-group','Key':'Project','Value':'itmo-544-final','PropagateAtLaunch':True}])


def deploy(cfg,aws):
    """Create everything in dependency order; do not send secrets in user data."""
    aws['ssm'].get_parameter(Name=cfg['GEMINI_KEY_PARAM'],WithDecryption=False)
    account=aws['sts'].get_caller_identity()['Account']
    for key in ('FACTS_TABLE_NAME','REPORT_TABLE_NAME','COUNTER_TABLE_NAME'):
        ensure_table(aws['dynamodb'],cfg[key])
    topic=ensure_topic(aws['sns'],cfg['SNS_TOPIC_NAME'])
    for tier in ('weather','advisor'):
        ensure_role(aws['iam'],cfg[tier.upper()+'_ROLE_NAME'],cfg[tier.upper()+'_PROFILE_NAME'],role_policy(tier,cfg,account,topic))
    time.sleep(15)
    ec2=aws['ec2']
    vpc=next((v['VpcId'] for v in ec2.describe_vpcs(Filters=[{'Name':'isDefault','Values':['true']}])['Vpcs']),None)
    if not vpc:raise RuntimeError('No default VPC')
    subnets=[]
    for az in ('AZ_A','AZ_B'):
        result=ec2.describe_subnets(Filters=[{'Name':'vpc-id','Values':[vpc]},{'Name':'availability-zone','Values':[cfg[az]]}])['Subnets']
        if not result:raise RuntimeError('No subnet in '+cfg[az])
        subnets.append(result[0]['SubnetId'])
    sg=ensure_alb_sg(aws,cfg,vpc)
    targets={tier:ensure_target(aws,cfg[tier.upper()+'_TG_NAME'],vpc) for tier in ('weather','advisor')}
    arn,dns=ensure_alb(aws,cfg,subnets,sg)
    for tier in targets:ensure_listener(aws['elbv2'],arn,int(cfg[tier.upper()+'_LISTENER_PORT']),targets[tier])
    base=Path(__file__).resolve().parent
    environments={
        'weather':{'NWS_USER_AGENT':f"(ITMO 544 Weather Advisor, {cfg['CONTACT_EMAIL']})",'FACTS_TABLE_NAME':cfg['FACTS_TABLE_NAME'],'CACHE_SECONDS':cfg.get('CACHE_SECONDS','600'),'STALE_SECONDS':cfg.get('STALE_SECONDS','86400'),'API_TIMEOUT_MS':cfg.get('API_TIMEOUT_MS','5000'),'HEAVY_RAIN_MM':cfg.get('HEAVY_RAIN_MM','7.6'),'HEAVY_SNOW_MM':cfg.get('HEAVY_SNOW_MM','5')},
        'advisor':{'WEATHER_URL':f"http://{dns}:{cfg['WEATHER_LISTENER_PORT']}",'REPORT_TABLE_NAME':cfg['REPORT_TABLE_NAME'],'COUNTER_TABLE_NAME':cfg['COUNTER_TABLE_NAME'],'GEMINI_KEY_PARAM':cfg['GEMINI_KEY_PARAM'],'GEMINI_MODEL':cfg['GEMINI_MODEL'],'SNS_TOPIC_ARN':topic,'GEMINI_DAILY_CAP':cfg.get('GEMINI_DAILY_CAP','30'),'REPORT_CACHE_SECONDS':cfg.get('REPORT_CACHE_SECONDS','600'),'VISITOR_REPORT_DAILY_LIMIT':cfg.get('VISITOR_REPORT_DAILY_LIMIT','20'),'VISITOR_EMAIL_DAILY_LIMIT':cfg.get('VISITOR_EMAIL_DAILY_LIMIT','3')},
    }
    for tier in targets:
        user_data=build_user_data(tier,cfg['AWS_REGION'],environments[tier],base)
        ensure_template(aws,cfg,tier,user_data)
        ensure_asg(aws,cfg,tier,targets[tier],subnets)
    output={'alb_dns':dns,'weather_url':f"http://{dns}:{cfg['WEATHER_LISTENER_PORT']}",'advisor_url':f"http://{dns}:{cfg['ADVISOR_LISTENER_PORT']}",'sns_topic_arn':topic}
    Path('stack_outputs.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='.env')
    args=parser.parse_args()
    cfg=settings(args.config)
    deploy(cfg,clients(cfg['AWS_REGION']))

if __name__=='__main__':main()
