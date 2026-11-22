# Report Definitions

## 1. Periods

For my project, users can choose today or any of the next six days. I set Morning from 6:00 AM to 11:59 AM and Night from 6:00 PM to 11:59 PM. The app uses the ZIP code's local timezone and accounts for daylight saving time.

Users can still select today if Morning has already passed. If the forecast has no data for that period, the app shows "not available."

## 2. Aggregation: one number per period

I use hourly weather data to calculate the values for each period.

| Weather Item | How It Works |
|---|---|
| Temperature | Lowest and highest temperatures in °F |
| Wind Speed | Highest sustained wind speed in mph |
| Visibility | Lowest visibility in miles |
| UV | Highest UV index |
| Humidity | Average humidity percentage |
| Rain | Highest hourly rainfall used to determine No, Mild, or Heavy |
| Snow | Highest hourly snowfall used to determine No, Mild, or Heavy |
| Road Conditions | Gemini gives advice based on the weather |
| Dressing | Gemini suggests clothing based on weather and clothing preference |
| Accessories | Gemini suggests useful items to carry |

NWS is my first choice for temperature, wind, and humidity. I use Open-Meteo when NWS is missing those values. Open-Meteo also provides visibility, UV, rain, and snow.

## 3. Heavy, Mild and No

I used fixed thresholds so the results stay consistent.

| Category | Rain | Snow |
|---|---|---|
| No | 0 mm | 0 mm |
| Mild | More than 0 but less than 7.6 mm | More than 0 but less than 5 mm |
| Heavy | 7.6 mm or more | 5 mm or more |

These are based on the highest hourly amounts. Open-Meteo gives snow in centimeters, so my code converts it to millimeters. Rain probability alone does not determine the category.

## 4. The three advice items

Road Conditions: Suggests whether roads might be wet, icy, or difficult to drive on based on rain, snow, temperature, wind, and visibility.

Dressing: Recommends clothing based on the temperature, wind, humidity, rain, snow, and the user's clothing preference.

Accessories: Suggests items like umbrellas, sunglasses, sunscreen, gloves, or scarves depending on the weather.

For clothing preferences, I included three options: gender-neutral, menswear, and womenswear. These are only used to personalize clothing suggestions. Gemini receives the clothing category, not the user's identity. The app also does not store or log the user's email address or gender together.
