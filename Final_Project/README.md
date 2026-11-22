# Final Project

## Project Overview

For my final project, I built a Weather Advisor application using my Lab06 project as a starting point. The app uses NWS and Open-Meteo for weather data, Gemini for recommendations, and Amazon SNS to email the reports. I also added a simple navy blue design and a timestamp showing when the report is being viewed.

## Challenges I Faced

One of the biggest challenges I faced was getting both applications to work together on AWS. I had issues with the website not displaying reports after making HTML and CSS changes. I also had trouble getting the CSS file to deploy correctly to EC2. Another challenge was troubleshooting AWS errors and making sure all resources were deleted after testing. 

## Testing

I tested the application using pytest, integration tests, and a chaos test. The application successfully generated reports, sent emails, and recovered after and EC2 instance was terminated. I also tested to make sure the application showed an error message if the zipcode or email wasn't correct.

## What I Learned

This project helped me better understand how AWS services work together in a real application. I learned more about using EC2, Auto Scaling, DynamoDB, and load balancers. I also gained experience troubleshooting Node.js applications, connecting APIs, testing instance recovery, and managing AWS costs. Overall, I became more comfortable deploying and debugging a cloud application on my own. 
