# AWS CLI EC2 EnvVariables

## aws ec2 describe-instances labeled

1. aws is the AWS Command Line Interface (CLI). It's the tool that lets me run AWS commands directly from my terminal instead of going through the console. When I type aws into the terminal, I'm telling the computer to communicate directly with AWS services. 

2. ec2 is the service that tells the CLI which AWS service I want to interact with. EC2 stands for Elastic Compute Cloud and it handles anything related to compute resources like virtual machines and security groups. 

3. The describe-instances operation is the API call that I'm making inside the EC2 service. In this command, "describe" means I'm asking AWS to return all the metadata about the the ec2 instances. This includes things like instance ID, instance type, security groups etc. It gives a detailed view of each instance. 

4. The parameters are the extra parts of the command that narrow down what the describe-instances operation returns. I can specify things like a specific instance ID or a region to look in. Parameters also let me control what the output looks like, so instead of getting every instance by default, I can target exactly what I want to see.

## Hello From Web page
![Hello From Web page](./screenshots/hello-from-ss.png)

## Git Status Output
![git status for .env](./screenshots/git-status-ss.png)

## create_instances.sh Output
![create_instances.sh output](./screenshots/create-instances-ss.png)

## delete_instances.sh Output
![delete_instances.sh output](./screenshots/delete-instances-ss.png)

## Link to GitHub Repo
https://github.com/scuevas1/cloud-computing-suheily 

## Why are environment files excluded from Git, even in a “private” repository?

Environment files should always be excluded from Git because they usually contain sensitive information that shouldn’t be shared, even in a private repo. For this assignment, my .env file stored values like my AWS region, AMI ID, and security group. These settings tell my script exactly what to launch, but they’re unique to my environment and could expose details about my AWS setup if they were pushed to Git. The .env files stay out of version control using .gitignore because they hold environment specific configuration that can leak secrets, so they stay local on my machine where they are used at runtime, not in Git where code is shared.