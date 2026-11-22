# Final Project Reflection

## What I Would Change With 10 Times More Traffic

If my weather advisor application had 10 times more users, I would first focus on making sure the application could handle everyone without slowing down. I already use Auto Scaling Groups for both the Weather and Advisor applications, but I would improve the scaling settings so more EC2 instances could start automatically when the traffic begins to increase. The recovery worked, but it took around 157 seconds. With more users, I would want that recovery to happen faster so fewer people would be affected. 

I would also improve the caching system. Right now, DynamoDB stores weather information and reports so the application does not have to make the same API requests multiple times. When I tested my application, my repeated report request was definitely faster than the first one. With more traffic, my caching would become even more important because many users might search for the same ZIP code and date. This would also help reduce requests to Gemini and the weather APIs.

Another change I would make is improving the request limits. If AWS creates more instances, they would each track requests separately I would move those limits into DynamoDB so they work across the entire application.

## What I Would Change Before Putting Into Real Use

One thing I would change before putting it into real use make the recommendations more useful for each person's actual day. Right now the application gives advice based on the weather and clothing preference. I would add an option where users can pick what they are planning to do during the day, like driving to work, walking to class, or exercising. Someone walking to class in the snow might need a different clothing recommendation than someone that is just driving to work. 

Another thing I would change is a road conditions feature. Right now Gemini uses weather data to suggest what roads might be like. If I were making this a real application, I would want to connect it to actual road-confition data so users could see up to date information about icy roads, traffic issues, or road closures instead of relying only on weather-based predictions. 

I would also improve the timestamp feature that I added. Right now if just shows when someone views the report, but that doesn't mean the weather information was updated at that time. I would change it to show when the forecast was last updated by NWS and Open-Meteo. That way, the users would have a better idea of how recent the weather information actually is. 