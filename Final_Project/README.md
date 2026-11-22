# Lab 06 - Weather Advisor in the Cloud

## Project Overview

For this lab, I built a two-tier weather application using AWS and Python. The weather service gets weather information and stores it in a PostgreSQL database, while the advisor uses Gemini AI to recommend what to wear. I also used Python and boto3 to create and delete the AWS resources.

## Challenges I Faced

One of my biggest challenges was understanding how to switch everything from Bash scripts to Python. I had to figure out how to use boto3 to manage AWS resources while making sure everything still worked the same way.

I also ran into issues with IAM permissions and Gemini returning 503 errors even though my API key was working. Another challenge was getting my chaos tests to pass, especially when I had to change how the weather service restarted because of IAM permission issues.

## Test Results

- Unit tests: 28 passed
- Integration tests: 12 passed
- Chaos tests: 2 passed
- EC2 recovery time: 89.39 seconds

## What I Learned

Overall, this lab helped me better understand how AWS services work together, how to troubleshoot problems, and how to use Python to automate cloud infrastructure.
