# Weather Advisor: Architecture and Design Decisions

## 1. Project Overview

For my ITMO 544 final project, I built a Weather Advisor application using my Lab06 project as a starting point. I kept the two Node.js applications and used Python to deploy and manage the AWS resources.

Users enter a US ZIP code, date, clothing preference, and email address. The application generates Morning and Night weather reports with seven weather items and three recommendations.

I use NWS and Open-Meteo for weather data, Gemini for recommendations, and Amazon SNS to email reports. I also added a timestamp that shows when the user views the report.

## 2. Architecture Diagram

```text
                  User Browser
                       |
                       v
            Application Load Balancer
               /               \
          Port 8080          Port 8081
              |                  |
              v                  v
         Weather Tier       Advisor Tier
         EC2 + ASG          EC2 + ASG
         Node.js            Node.js
         Port 3000          Port 3000
              ^                  |
              |                  |
              +--- Weather API --+
              |                  |
       ZIP Lookup, NWS,       Gemini API
          Open-Meteo         SNS Email
              |              SSM Key
              v                  |
       DynamoDB Facts       DynamoDB Reports
            Cache             and Counter
```

The Weather tier handles weather information, while the Advisor tier handles the website, recommendations, and email. Both applications run on EC2 instances managed by Auto Scaling Groups.

## 3. Components and Responsibilities

| Component | Responsibility |
|---|---|
| Load Balancer | Routes requests to the Weather and Advisor applications and checks target health. |
| Weather Tier | Gets weather data, calculates weather categories, and caches results. |
| Advisor Tier | Displays the website, gets weather data, generates Gemini advice, handles emails, and displays the report-viewed timestamp. |
| ZIP Lookup | Uses the ZIP code API already provided in Lab06 to find coordinates. |
| NWS | Provides forecast information and the local timezone. |
| Open-Meteo | Provides additional weather measurements. |
| Gemini | Generates road, clothing, and accessory recommendations. |
| DynamoDB | Stores weather facts, reports, and Gemini usage counters. |
| SNS | Sends weather reports through confirmed email subscriptions. |
| SSM | Securely stores the Gemini API key. |
| IAM | Controls what each application can access in AWS. |
| Python Scripts | Create, configure, and delete the AWS infrastructure. |

## 4. Report Generation

1. The user enters a ZIP code, date, clothing preference, and email.
2. The Advisor validates the information.
3. The Advisor checks whether a cached report is available.
4. If needed, it requests weather information from the Weather tier.
5. The Weather tier gets data from NWS and Open-Meteo and calculates the weather values.
6. The Advisor sends the weather facts and clothing category to Gemini for recommendations.
7. If Gemini fails or reaches its limit, the application uses backup recommendations.
8. The report displays all 10 items for Morning and Night, along with the available weather sources.
9. My extra timestamp feature shows when the report page is viewed using the user's local device time.

## 5. Email Delivery

1. The user enters an email address and generates the report.
2. The user checks the consent box and clicks Email My Report.
3. If needed, SNS sends a subscription confirmation email.
4. Once confirmed, the user can request delivery again.
5. SNS uses recipient-specific filtering to send the requested report.
6. The website displays whether the email request is pending, accepted, or failed.

The email address is not sent to Gemini. SNS accepting a message does not guarantee that the email reaches the inbox.

## 6. Weather Data and Recommendations

| Item | Source |
|---|---|
| Temperature | NWS, with Open-Meteo as backup |
| Wind Speed | NWS, with Open-Meteo as backup |
| Visibility | Open-Meteo |
| UV Index | Open-Meteo |
| Humidity | NWS, with Open-Meteo as backup |
| Rain | Open-Meteo data, categorized by my code |
| Snow | Open-Meteo data, categorized by my code |
| Road Conditions | Gemini or backup rules |
| Dressing | Gemini or backup rules |
| Accessories | Gemini or backup rules |

Gemini does not generate weather measurements. If a weather value is missing, the application shows it as unavailable instead of assuming it is zero.

## 7. Design Decisions

| # | Decision | What I Chose and Why |
|---|---|---|
| 1 | Application tiers | I kept two tiers instead of combining everything into one. This separates weather processing from recommendations and email. |
| 1a | Programming language | I kept Node.js from Lab06 instead of rewriting the application in Python. Python handles the AWS infrastructure. |
| 2 | Weather sources | I chose NWS and Open-Meteo instead of relying on NWS alone or asking Gemini for missing values. |
| 3 | ZIP lookup | I reused Lab06's Zippopotam.us API instead of asking users for coordinates. Invalid and unknown ZIP codes are handled separately. |
| 4 | Morning and Night | I use 6:00–11:59 AM for Morning and 6:00–11:59 PM for Night. I chose local time instead of UTC, including daylight saving time. Users can select today through six days ahead. |
| 5 | Weather calculations | I use temperature ranges, maximum wind, minimum visibility, maximum UV, average humidity, and peak hourly rain/snow instead of using one random hourly value. |
| 6 | Rain and snow categories | I use fixed thresholds instead of Gemini-generated labels. Heavy rain starts at 7.6 mm/hour and heavy snow at 5 mm/hour. Values above zero but below these limits are Mild, while zero is No. These are my project's thresholds. |
| 7 | Caching | I chose DynamoDB instead of only local memory. Weather facts and reports are fresh for 600 seconds, and weather facts can be reused as stale data during an outage for up to 86,400 seconds. |
| 8 | Gemini | I chose structured JSON instead of unrestricted text. The application validates the response and limits Gemini to 30 calls per UTC day. The model is configurable. |
| 9 | Gemini failures | I use rule-based recommendations instead of failing the whole report when Gemini is unavailable. |
| 10 | Email service | I chose SNS instead of SES because confirmed subscriptions work for this project. Recipient-specific filtering is needed to keep reports private. |
| 11 | IAM permissions | I use separate restricted roles instead of one role with broad access. Weather accesses the facts table. Advisor accesses reports, counters, its specific SSM key, and the SNS topic. |
| 12 | Abuse prevention | I use validation, caching, and request limits instead of allowing unlimited requests. The app limits each visitor to 20 report requests and 3 email requests per day per instance. |
| 13 | Cost and API limits | I use an atomic DynamoDB counter for Gemini limits and budget.py to estimate expenses. I delete the AWS stack after testing to stay under $2. |
| 14 | Clothing preference | I use Gender-neutral, Menswear, and Womenswear instead of a free-text gender field. The preference is only for clothing recommendations and is not stored with the email address. |

## 8. Security and Risks

| Risk | How I Handle It |
|---|---|
| Invalid user input | Validate ZIP code, date, clothing category, and email on the server. Escape HTML output. |
| Incorrect weather information | Use weather APIs for measurements and Gemini only for advice. |
| Exposed API keys | Store the Gemini key in SSM SecureString. |
| Unauthorized AWS access | Use restricted IAM roles and security groups. |
| Too many Gemini requests | Use a daily DynamoDB counter and cached reports. |
| Email privacy | Require consent, confirmed subscriptions, and recipient-specific SNS filters. |
| Weather API failure | Use available cached facts or show an error. |
| Gemini failure | Use backup recommendations and label them as fallback. |
| EC2 failure | Auto Scaling replaces failed instances. |
| Unexpected AWS costs | Track usage and delete resources after testing. |

Some security features, especially SNS recipient isolation and IAM restrictions, still require separate verification.

## 9. Additional Feature

I added a Report Viewed At timestamp as an extra feature. It shows the date and time when the user opens the report page. I used JavaScript for this, so it does not require another API or AWS service.

The timestamp uses the user's device time. It does not represent when NWS or Open-Meteo last updated their forecasts.
