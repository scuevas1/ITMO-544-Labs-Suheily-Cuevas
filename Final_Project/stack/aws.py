"""AWS clients, IAM policies and DynamoDB table lifecycle."""
import json
import boto3
from botocore.exceptions import ClientError


def clients(region):
    """Build the boto3 clients for the selected region."""
    session = boto3.Session(region_name=region)
    return {key: session.client(service) for key, service in {'ec2':'ec2','iam':'iam','elbv2':'elbv2','asg':'autoscaling','dynamodb':'dynamodb','ssm':'ssm','sns':'sns','sts':'sts'}.items()}


def code(error):
    return error.response.get('Error', {}).get('Code', '')


def ignore_missing(function, *codes):
    try:
        return function()
    except ClientError as exc:
        if code(exc) not in codes:
            raise


def ensure_table(db, name):
    """Create an on-demand, TTL-enabled table if absent."""
    try:
        db.describe_table(TableName=name)
    except db.exceptions.ResourceNotFoundException:
        db.create_table(TableName=name, BillingMode='PAY_PER_REQUEST', KeySchema=[{'AttributeName':'pk','KeyType':'HASH'}], AttributeDefinitions=[{'AttributeName':'pk','AttributeType':'S'}])
    db.get_waiter('table_exists').wait(TableName=name)
    ttl = db.describe_time_to_live(TableName=name).get('TimeToLiveDescription', {})
    if ttl.get('TimeToLiveStatus', 'DISABLED') == 'DISABLED':
        db.update_time_to_live(TableName=name, TimeToLiveSpecification={'Enabled':True,'AttributeName':'expiresAt'})


def table_policy(actions, arn):
    return {'Effect':'Allow','Action':actions,'Resource':arn}


def role_policy(tier, cfg, account, topic_arn):
    """Minimal per-tier policy, with concrete ARNs and no wildcard resources."""
    region = cfg['AWS_REGION']
    table = lambda name: f'arn:aws:dynamodb:{region}:{account}:table/{cfg[name]}'
    if tier == 'weather':
        statements = [table_policy(['dynamodb:GetItem','dynamodb:PutItem'], table('FACTS_TABLE_NAME'))]
    else:
        statements = [
            table_policy(['dynamodb:GetItem','dynamodb:PutItem'], table('REPORT_TABLE_NAME')),
            table_policy(['dynamodb:UpdateItem'], table('COUNTER_TABLE_NAME')),
            table_policy(['ssm:GetParameter'], f"arn:aws:ssm:{region}:{account}:parameter{cfg['GEMINI_KEY_PARAM']}"),
            table_policy(['sns:Subscribe','sns:Publish','sns:ListSubscriptionsByTopic'], topic_arn),
        ]
    return {'Version':'2012-10-17','Statement':statements}


def ensure_role(iam, name, profile, policy):
    """Create/update an EC2 role and instance profile idempotently."""
    trust = {'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'ec2.amazonaws.com'},'Action':'sts:AssumeRole'}]}
    try:
        iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust))
    except ClientError as exc:
        if code(exc) != 'EntityAlreadyExists': raise
    try:
        iam.create_instance_profile(InstanceProfileName=profile)
    except ClientError as exc:
        if code(exc) != 'EntityAlreadyExists': raise
    existing = iam.get_instance_profile(InstanceProfileName=profile)['InstanceProfile']['Roles']
    if existing and existing[0]['RoleName'] != name:
        raise RuntimeError('Instance profile belongs to another role')
    if not existing:
        iam.add_role_to_instance_profile(InstanceProfileName=profile, RoleName=name)
    iam.put_role_policy(RoleName=name, PolicyName=name+'-policy', PolicyDocument=json.dumps(policy))


def ensure_topic(sns, name):
    """Get the ARN of a single private email topic."""
    return sns.create_topic(Name=name)['TopicArn']
