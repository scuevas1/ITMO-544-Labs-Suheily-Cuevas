# Lab 06 - Short Answers

## Comparing the Python and bash versions of the same step

When comparing the Python and Bash versions for creating the database and waiting for it to become available, I found that Bash was easier to understand just because I'm more familiar with AWS CLI commands. Python was a little more challenging because I had to understand how to use boto3 to create resources and check their status. But, Python was definitely easier to test because I could use pytest and moto to simulate the database creation without actually using AWS resources. Overall, I would say Bash was easier for me to understand and create, but Python was easier for testing. 