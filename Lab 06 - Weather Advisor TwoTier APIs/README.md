# Lab 06 — Weather Advisor TwoTier APIs

**Name:** Suheily Cuevas                 
**Course:** ITMO 544 — Cloud Computing  
**Section:** 16.2 — Graduate Students Only (Python)

## Project Overview

For this lab, I built a two-tier weather application using AWS and Python. The weather service gets weather information and caches it in PostgreSQL, while the advisor uses Gemini AI to give clothing recommendations.

## Challenges

One of my biggest challenges was figuring out how to switch everything from Bash scripts to Python using boto3. I also ran into some IAM permission issues and Gemini API errors that I had to troubleshoot.

Another challenge was getting my chaos tests working correctly, especially testing how the application responds when the database or an EC2 instance goes down.

## Test Results

| Test | Result |
|---|---|
| Unit tests (moto) | 28 passed |
| Integration tests | 12 passed |
| Chaos tests | 2 passed |
| Weather instance recovery | 89.39 seconds |
| Unit tests without AWS credential environment variables | 28 passed |

## Conclusion

This lab helped me better understand how to automate AWS infrastructure using Python and troubleshoot issues across multiple AWS services.