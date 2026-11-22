# Weather Advisor API Source Map

## 1. Overview

For my project, I used the National Weather Service (NWS) as the main weather source. I added Open-Meteo for information that NWS does not always provide. I also used Zippopotam.us to turn a ZIP code into coordinates. My weather app handles the actual measurements and calculates the rain and snow categories. Gemini is only used for recommendations, not for weather measurements.

## 2. ZIP Codes and Forecast Times

I kept the ZIP code lookup API that was already provided in Lab06. It uses Zippopotam.us to convert a five-digit US ZIP code into latitude and longitude. I reused this part of the original code instead of adding another API for ZIP code lookup. If the ZIP code does not exist, the application returns a clear error message.

## 3. Where Each Report Item Comes From

The app uses the same rules for Morning and Night. It only uses the forecast hours that fall within each period.

| Output | API endpoint and exact field | Unit and period aggregation | Gap handling |
|---|---|---|---|
| Temperature | NWS properties.periods[].temperature from properties.forecastHourly; fallback Open-Meteo hourly.temperature_2m | °F, minimum–maximum range | Use Open-Meteo if no usable NWS values; otherwise not available |
| Wind speed | NWS properties.periods[].windSpeed; fallback Open-Meteo hourly.wind_speed_10m | mph, maximum sustained wind | Open-Meteo fallback, otherwise not available |
| Visibility | Open-Meteo hourly.visibility | meters converted to miles, minimum | Not available if missing |
| UV index | Open-Meteo hourly.uv_index | UV index, maximum | Not available if missing |
| Humidity | NWS properties.periods[].relativeHumidity.value; fallback Open-Meteo hourly.relative_humidity_2m | %, arithmetic average | Open-Meteo fallback, otherwise not available |
| Rain | Open-Meteo hourly.rain; hourly.precipitation_probability is supplementary only | Peak hourly rain (mm), code-derived category | Heavy at ≥ 7.6 mm; Mild above 0 and below 7.6; No at 0; missing amount = not available |
| Snow | Open-Meteo hourly.snowfall | Peak hourly snowfall converted from cm to mm, code-derived category | Heavy at ≥ 5 mm; Mild above 0 and below 5; No at 0; missing amount = not available |
| Road conditions | Gemini response morning.road / night.road | Short advice text | Rule-based fallback when Gemini fails or is limited |
| Suggested dressing | Gemini response morning.dressing / night.dressing | Short advice using the chosen clothing category | Rule-based fallback |
| Suggested accessories | Gemini response morning.accessories / night.accessories | Short advice text | Rule-based fallback |

The Heavy, Mild, and No categories are calculated by my code. They are not categories returned directly by Open-Meteo.

## 4. Real API Examples

| Source | Endpoint used | Exact field | Actual value and local timestamp | Observed coverage and resolution |
|---|---|---|---|---|
| Zippopotam.us | https://api.zippopotam.us/us/60616 | places[0].latitude, places[0].longitude | TODO: copy actual response | Point lookup |
| NWS points | https://api.weather.gov/points/{lat},{lon} | properties.timeZone, properties.forecastHourly | TODO: copy actual response | Location and hourly forecast link |
| NWS hourly | URL from properties.forecastHourly | properties.periods[].startTime, .temperature, .windSpeed, .relativeHumidity.value | TODO: add real Morning and Night examples | TODO: record first/last timestamp |
| Open-Meteo | https://api.open-meteo.com/v1/forecast with app's hourly parameter list | hourly.temperature_2m, wind_speed_10m, relative_humidity_2m, visibility, uv_index, rain, snowfall, precipitation_probability | TODO: add real Morning and Night examples for each measurement | Hourly; request seven forecast days |
| Gemini | models/{GEMINI_MODEL}:generateContent | Validated advice fields morning and night (road, dressing, accessories) | TODO: record only non-personal example advice | Not a measurement source |

### Other Evidence I Still Need

- A real example where a weather value is missing, showing that the report says not available instead of zero.
- The first and last forecast timestamps returned by NWS, so I can show how far ahead its data actually goes.
- The documented API usage limits and attribution requirements for the weather sources.

## 5. Why I Used These APIs

NWS was required for the project, and it works well for US forecasts. The issue is that it does not always give every measurement I need for all seven days. That is why I added Open-Meteo for things like visibility, UV, rain, and snow. Its free non-commercial API also fits the small budget for this class project. Zippopotam.us makes the form easier to use because people can enter a ZIP code instead of coordinates. I show which API each value came from so the report is clear about its sources. If a value is missing, I show that it is unavailable rather than treating it as zero.

## 6. API Documentation

- NWS API: https://www.weather.gov/documentation/services-web-api
- Open-Meteo forecast API: https://open-meteo.com/en/docs
- Zippopotam.us: https://www.zippopotam.us/
- Gemini API documentation: https://ai.google.dev/gemini-api/doc
