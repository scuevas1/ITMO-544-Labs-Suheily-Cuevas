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

The examples below use ZIP 60616 and my saved report for November 21, 2026. The saved report contains aggregated Morning and Night results, not copies of the original hourly API responses. I have identified any information that was not preserved instead of inventing it.

| Source | Endpoint used | Exact field | Actual value and local timestamp | Observed coverage and resolution |
|---|---|---|---|---|
| Zippopotam.us | https://api.zippopotam.us/us/60616 | places[0].latitude, places[0].longitude | Latitude 41.8426, longitude -87.6306 (Chicago, Illinois; verified from the ZIP API response). | Point lookup |
| NWS points | https://api.weather.gov/points/41.8426,-87.6306 | properties.timeZone, properties.forecastHourly | For Chicago, the applicable local time zone is America/Chicago. The app requests properties.timeZone and properties.forecastHourly; the exact raw forecastHourly URL and returned point fields were not saved, so I can't quote them as observed. | Location and hourly forecast link |
| NWS hourly | URL from properties.forecastHourly | properties.periods[].startTime, .temperature, .windSpeed, .relativeHumidity.value | From my saved November 21, 2026 report, Night (6:00–11:59 PM Chicago local time): temperature 55–60 °F, wind 10 mph, humidity 58.2%; all labeled NWS. These are aggregated report readings, not individual hourly payload values. Morning NWS-specific reading not preserved in this evidence. | Hourly forecasts. The application retrieves hourly forecast records from the NWS forecastHourly endpoint. Each record includes a startTime timestamp. The first and last timestamps define the available forecast period, with approximately hourly resolution; the saved report does not include them. |
| Open-Meteo | https://api.open-meteo.com/v1/forecast?latitude=41.8426&longitude=-87.6306&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,visibility,uv_index,precipitation_probability,rain,snowfall&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=mm&timezone=America%2FChicago&forecast_days=7 with app's hourly parameter list | hourly.temperature_2m, wind_speed_10m, relative_humidity_2m, visibility, uv_index, rain, snowfall, precipitation_probability | From my saved November 21, 2026 report, Morning (6:00–11:59 AM Chicago local time): temperature 46.4–63.6 °F, wind 7.7 mph, visibility 10.4 miles, UV index 2.5, humidity 69.3%, rain No, snow No. Night (6:00–11:59 PM): visibility 18.5 miles, UV 0, rain No, snow No. These are processed report values, not raw hourly readings. | Hourly forecast data requested for seven days. The app groups hourly measurements into Morning and Night using Chicago local time. Exact first and last hourly timestamps were not preserved in the saved report. |
| Gemini | models/{GEMINI_MODEL}:generateContent | Validated advice fields: morning.road,morning.dressing, morning.accessories, night.road, night.dressing, and night.accessories | Saved report for November 21, 2026 (ZIP 60616). Morning road advice: "Clear roads with excellent visibility for your commute." Morning dressing: "Layering is recommended as temperatures rise from cool to mild." Morning accessories: "Sunglasses are helpful for the morning sun." | AI-generated recommendations for Morning and Night. Not a weather measurement source. |

### Other Evidence I Still Need

- Missing weather values: If my app cannot get a weather measurement, it shows "Not available" instead of putting zero. I tested this in my Weather app unit tests, and the test passed. I just didn't save an actual API response where data was missing.
- NWS forecast coverage: My app uses the startTime from NWS to figure out which hours belong to Morning and Night. I didn't save the exact first and last timestamps from the original response, but I also use Open-Meteo to get hourly forecasts for the next seven days.
- API usage limits and attribution: NWS is free to use, but it has rate limits and requires a User-Agent header. Open-Meteo allows up to 10,000 calls per day on its free non-commercial plan and requires attribution. Zippopotam.us also provides free ZIP code lookups. I used caching to avoid making unnecessary API calls and included the weather sources in my reports.

## 5. Why I Used These APIs

NWS was required for the project, and it works well for US forecasts. The issue is that it does not always give every measurement I need for all seven days. That is why I added Open-Meteo for things like visibility, UV, rain, and snow. Its free non-commercial API also fits the small budget for this class project. Zippopotam.us makes the form easier to use because people can enter a ZIP code instead of coordinates. I show which API each value came from so the report is clear about its sources. If a value is missing, I show that it is unavailable rather than treating it as zero.

## 6. API Documentation

- NWS API: https://www.weather.gov/documentation/services-web-api
- Open-Meteo forecast API: https://open-meteo.com/en/docs
- Zippopotam.us: https://docs.zippopotam.us/
- Gemini API documentation: https://ai.google.dev/gemini-api/docs
