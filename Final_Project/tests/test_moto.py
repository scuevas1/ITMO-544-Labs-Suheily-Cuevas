"""moto tests for the created DynamoDB and SNS resources."""
import boto3
from moto import mock_aws
from stack.aws import ensure_table, ensure_topic


def test_dynamodb_create_twice_and_delete():
    with mock_aws():
        client = boto3.client('dynamodb', region_name='us-east-2')
        ensure_table(client, 'itmo-544-final-facts')
        ensure_table(client, 'itmo-544-final-facts')
        result = client.describe_table(TableName='itmo-544-final-facts')['Table']
        assert result['BillingModeSummary']['BillingMode'] == 'PAY_PER_REQUEST'
        assert client.describe_time_to_live(TableName='itmo-544-final-facts')['TimeToLiveDescription']['AttributeName'] == 'expiresAt'
        client.delete_table(TableName='itmo-544-final-facts')


def test_sns_topic_create_twice():
    with mock_aws():
        sns = boto3.client('sns', region_name='us-east-2')
        name = 'itmo-544-final-email'
        assert ensure_topic(sns, name) == ensure_topic(sns, name)
