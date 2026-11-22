'use strict';

const express = require('express');
const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const {
  DynamoDBDocumentClient,
  GetCommand,
  PutCommand
} = require('@aws-sdk/lib-dynamodb');

const app = express();

const PORT = Number(process.env.PORT || 3000);
const ZIP_API = process.env.ZIP_API_BASE || 'https://api.zippopotam.us';
const NWS_API = process.env.NWS_API_BASE || 'https://api.weather.gov';
const METEO_API = process.env.METEO_API_BASE || 'https://api.open-meteo.com/v1/forecast';

const USER_AGENT = process.env.NWS_USER_AGENT ||
  '(ITMO 544 Weather Advisor, student@example.com)';

const TABLE_NAME = process.env.FACTS_TABLE_NAME || '';
const CACHE_SECONDS = Number(process.env.CACHE_SECONDS || 600);
const STALE_SECONDS = Number(process.env.STALE_SECONDS || 86400);
const API_TIMEOUT_MS = Number(process.env.API_TIMEOUT_MS || 5000);

const HEAVY_RAIN_MM = Number(process.env.HEAVY_RAIN_MM || 7.6);
const HEAVY_SNOW_MM = Number(process.env.HEAVY_SNOW_MM || 5);

const db = TABLE_NAME
  ? DynamoDBDocumentClient.from(new DynamoDBClient({
      region: process.env.AWS_REGION
    }))
  : null;

function log(event, details = {}) {
  console.log(JSON.stringify({
    timestamp: new Date().toISOString(),
    event,
    ...details
  }));
}

class WeatherError extends Error {
  constructor(message, status = 502, stage = 'weather') {
    super(message);
    this.status = status;
    this.stage = stage;
  }
}

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function round(value, places = 1) {
  return isNumber(value)
    ? Number(value.toFixed(places))
    : null;
}

function average(values) {
  const valid = values.filter(isNumber);
  if (!valid.length) return null;
  return valid.reduce((a, b) => a + b, 0) / valid.length;
}

function maximum(values) {
  const valid = values.filter(isNumber);
  return valid.length ? Math.max(...valid) : null;
}

function minimum(values) {
  const valid = values.filter(isNumber);
  return valid.length ? Math.min(...valid) : null;
}

function validateZip(zip) {
  if (typeof zip !== 'string' || !/^[0-9]{5}$/.test(zip)) {
    throw new WeatherError(
      'This service covers US locations only. Enter a five-digit US ZIP code.',
      400,
      'validation'
    );
  }
  return zip;
}

function localParts(date, zone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(date);

  const data = Object.fromEntries(
    parts.filter(p => p.type !== 'literal')
      .map(p => [p.type, p.value])
  );

  return {
    date: `${data.year}-${data.month}-${data.day}`,
    hour: Number(data.hour)
  };
}

function validateDate(input, timeZone) {
  if (typeof input !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(input)) {
    throw new WeatherError('Enter a valid date.', 400, 'validation');
  }

  const parsed = new Date(`${input}T12:00:00Z`);

  if (Number.isNaN(parsed.getTime()) ||
      parsed.toISOString().slice(0, 10) !== input) {
    throw new WeatherError('Invalid calendar date.', 400, 'validation');
  }

  const today = localParts(new Date(), timeZone).date;
  const start = Date.parse(`${today}T00:00:00Z`);
  const requested = Date.parse(`${input}T00:00:00Z`);
  const day = 86400000;

  if (requested < start || requested > start + 6 * day) {
    throw new WeatherError(
      'Choose a date from today through the next six days.',
      400,
      'validation'
    );
  }

  return input;
}

function periodName(hour) {
  if (hour >= 6 && hour < 12) return 'morning';
  if (hour >= 18 && hour < 24) return 'night';
  return null;
}

async function fetchJSON(url, stage, headers = {}) {
  let lastError;

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(url, {
        headers,
        signal: AbortSignal.timeout(API_TIMEOUT_MS)
      });

      if (response.status === 404) {
        return null;
      }

      if (!response.ok) {
        if (response.status < 500 && response.status !== 429) {
          throw new WeatherError(
            `${stage} rejected the request.`,
            502,
            stage
          );
        }
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();

    } catch (error) {
      lastError = error;

      if (error instanceof WeatherError) throw error;
      if (attempt === 0) {
        await new Promise(resolve => setTimeout(resolve, 250));
      }
    }
  }

  log('upstream_failure', { stage });

  throw new WeatherError(
    `Weather source unavailable: ${stage}`,
    502,
    stage
  );
}

async function lookupZip(zip) {
  const data = await fetchJSON(
    `${ZIP_API}/us/${zip}`,
    'zip_lookup'
  );

  if (!data || !Array.isArray(data.places) ||
      data.places.length === 0) {
    throw new WeatherError('ZIP code not found.', 404, 'zip_lookup');
  }

  const place = data.places[0];
  const latitude = Number(place.latitude);
  const longitude = Number(place.longitude);

  if (!isNumber(latitude) || !isNumber(longitude)) {
    throw new WeatherError(
      'Location coordinates unavailable.',
      502,
      'zip_lookup'
    );
  }

  return {
    zip,
    city: place['place name'],
    state: place['state abbreviation'],
    latitude,
    longitude
  };
}

function nwsHeaders() {
  return {
    'User-Agent': USER_AGENT,
    'Accept': 'application/geo+json'
  };
}

async function getNWSPoint(location) {
  const url = `${NWS_API}/points/` +
    `${location.latitude},${location.longitude}`;

  const point = await fetchJSON(url, 'nws_points', nwsHeaders());

  if (!point || !point.properties) {
    throw new WeatherError(
      'No National Weather Service coverage for this ZIP code.',
      404,
      'nws_points'
    );
  }

  const props = point.properties;

  if (!props.forecastHourly || !props.timeZone) {
    throw new WeatherError(
      'NWS forecast endpoint or time zone unavailable.',
      502,
      'nws_points'
    );
  }

  return props;
}

async function getNWSHourly(url) {
  let parsed;

  try {
    parsed = new URL(url);
  } catch {
    throw new WeatherError('Invalid NWS forecast URL.', 502);
  }

  if (parsed.protocol !== 'https:' ||
      parsed.hostname !== 'api.weather.gov') {
    throw new WeatherError('Untrusted NWS forecast URL.', 502);
  }

  const result = await fetchJSON(
    parsed.href,
    'nws_hourly',
    nwsHeaders()
  );

  if (!result ||
      !Array.isArray(result.properties?.periods)) {
    throw new WeatherError(
      'NWS hourly forecast unavailable.',
      502,
      'nws_hourly'
    );
  }

  return result.properties.periods;
}

async function getMeteoForecast(location, timeZone) {
  const params = new URLSearchParams({
    latitude: String(location.latitude),
    longitude: String(location.longitude),
    hourly: [
      'temperature_2m',
      'relative_humidity_2m',
      'wind_speed_10m',
      'visibility',
      'uv_index',
      'precipitation_probability',
      'rain',
      'snowfall'
    ].join(','),
    temperature_unit: 'fahrenheit',
    wind_speed_unit: 'mph',
    precipitation_unit: 'mm',
    timezone: timeZone,
    timeformat: 'unixtime',
    forecast_days: '7'
  });

  const data = await fetchJSON(
    `${METEO_API}?${params}`,
    'open_meteo'
  );

  if (!data || !data.hourly ||
      !Array.isArray(data.hourly.time)) {
    throw new WeatherError(
      'Supplementary forecast unavailable.',
      502,
      'open_meteo'
    );
  }

  return data.hourly;
}

function selectNWS(periods, date, zone, name) {
  return periods.filter(p => {
    if (typeof p.startTime !== 'string') return false;

    const instant = new Date(p.startTime);
    if (Number.isNaN(instant.getTime())) return false;

    const local = localParts(instant, zone);
    return local.date === date && periodName(local.hour) === name;
  });
}

function selectMeteo(hourly, date, name, zone) {
  const indexes = [];

  for (let i = 0; i < hourly.time.length; i++) {
    const timestamp = hourly.time[i];
    if (!isNumber(timestamp)) continue;

    const local = localParts(new Date(timestamp * 1000), zone);
    if (local.date === date && periodName(local.hour) === name) {
      indexes.push(i);
    }
  }

  return indexes;
}

function meteoValues(hourly, indexes, field) {
  const data = hourly[field];

  if (!Array.isArray(data)) return [];

  return indexes.map(i => data[i]).filter(isNumber);
}

function nwsWindMph(value) {
  if (typeof value !== 'string') return null;

  const numbers = value.match(/\d+(?:\.\d+)?/g);
  if (!numbers || !numbers.length) return null;

  const speed = Math.max(...numbers.map(Number));

  if (/km\/h/i.test(value)) return speed * 0.621371;
  if (/mph/i.test(value)) return speed;

  return null;
}

function metric(value, unit, source, reason) {
  return {
    value: round(value),
    unit,
    source: isNumber(value) ? source : null,
    reason: isNumber(value)
      ? null
      : (reason || 'Forecast value not available')
  };
}

function rainCategory(amounts, probabilities) {
  const peak = maximum(amounts);
  const chance = maximum(probabilities);

  if (peak === null) {
    return {
      value: null,
      reason: chance === null
        ? 'Rain forecast unavailable'
        : `Rain amount unavailable; precipitation chance ${chance}%`
    };
  }

  if (peak >= HEAVY_RAIN_MM) {
    return { value: 'Heavy', reason: null };
  }
  return {
    value: peak > 0 ? 'Mild' : 'No',
    reason: null
  };
}

function snowCategory(amounts) {
  const peak = maximum(amounts);

  if (peak === null) {
    return {
      value: null,
      reason: 'Snowfall forecast unavailable'
    };
  }

  if (peak >= HEAVY_SNOW_MM) {
    return { value: 'Heavy', reason: null };
  }

  return {
    value: peak > 0 ? 'Mild' : 'No',
    reason: null
  };
}

function categoryMetric(result, source) {
  return {
    value: result.value,
    unit: null,
    source: result.value === null ? null : source,
    reason: result.reason
  };
}

function makePeriod(name, date, zone, nwsPeriods, meteo) {
  const nws = selectNWS(nwsPeriods, date, zone, name);
  const indexes = meteo
    ? selectMeteo(meteo, date, name, zone)
    : [];

  const values = field =>
    meteo ? meteoValues(meteo, indexes, field) : [];

  const nwsTemps = nws.map(p => p.temperature).filter(isNumber);
  const meteoTemps = values('temperature_2m');

  const temps = nwsTemps.length ? nwsTemps : meteoTemps;
  const tempSource = nwsTemps.length
    ? 'NWS'
    : 'Open-Meteo';

  const nwsWinds = nws.map(p => nwsWindMph(p.windSpeed))
    .filter(isNumber);
  const meteoWinds = values('wind_speed_10m');

  const winds = nwsWinds.length ? nwsWinds : meteoWinds;
  const windSource = nwsWinds.length
    ? 'NWS'
    : 'Open-Meteo';

  const nwsHumidity = nws.map(
    p => p.relativeHumidity?.value
  ).filter(isNumber);

  const meteoHumidity = values('relative_humidity_2m');

  const humidity = nwsHumidity.length
    ? nwsHumidity
    : meteoHumidity;

  const humiditySource = nwsHumidity.length
    ? 'NWS'
    : 'Open-Meteo';

  const visibilityMeters = values('visibility');
  const uvValues = values('uv_index');
  const rainAmounts = values('rain');
  const snowAmountsCm = values('snowfall');
  const probabilities = values('precipitation_probability');

  const snowAmountsMm = snowAmountsCm.map(v => v * 10);

  const temperature = {
    low: round(minimum(temps)),
    high: round(maximum(temps)),
    unit: '°F',
    source: temps.length ? tempSource : null,
    reason: temps.length ? null : 'Temperature unavailable'
  };

  return {
    period: name,
    date,

    temperature,

    windSpeed: metric(
      maximum(winds),
      'mph',
      windSource
    ),

    visibility: metric(
      minimum(visibilityMeters) === null
        ? null
        : minimum(visibilityMeters) / 1609.344,
      'miles',
      'Open-Meteo'
    ),

    uv: metric(
      maximum(uvValues),
      'UV index',
      'Open-Meteo'
    ),

    humidity: metric(
      average(humidity),
      '%',
      humiditySource
    ),

    rain: categoryMetric(
      rainCategory(rainAmounts, probabilities),
      'Open-Meteo / calculated'
    ),

    snow: categoryMetric(
      snowCategory(snowAmountsMm),
      'Open-Meteo / calculated'
    ),

    advice: null,

    sampleHours: {
      nws: nws.length,
      supplementary: indexes.length
    }
  };
}

function cacheKey(zip, date) {
  return `${zip}#${date}`;
}

async function getCached(zip, date) {
  if (!db) return null;

  try {
    const result = await db.send(new GetCommand({
      TableName: TABLE_NAME,
      Key: { pk: cacheKey(zip, date) }
    }));

    return result.Item || null;
  } catch {
    log('cache_read_failed');
    return null;
  }
}

async function saveCached(zip, date, report) {
  if (!db) return;

  const now = Math.floor(Date.now() / 1000);

  try {
    await db.send(new PutCommand({
      TableName: TABLE_NAME,
      Item: {
        pk: cacheKey(zip, date),
        savedAt: now,
        expiresAt: now + STALE_SECONDS,
        report
      }
    }));
  } catch {
    log('cache_write_failed');
  }
}

async function buildReport(zip, requestedDate, location, point) {
  const timeZone = point.timeZone;

  validateDate(requestedDate, timeZone);

  const [nwsResult, meteoResult] = await Promise.allSettled([
    getNWSHourly(point.forecastHourly),
    getMeteoForecast(location, timeZone)
  ]);

  const nwsPeriods = nwsResult.status === 'fulfilled'
    ? nwsResult.value
    : [];

  const meteo = meteoResult.status === 'fulfilled'
    ? meteoResult.value
    : null;

  if (!nwsPeriods.length && !meteo) {
    throw new WeatherError(
      'Weather data is temporarily unavailable.',
      502,
      'weather_sources'
    );
  }

  const morning = makePeriod(
    'morning', requestedDate, timeZone, nwsPeriods, meteo
  );

  const night = makePeriod(
    'night', requestedDate, timeZone, nwsPeriods, meteo
  );

  return {
    location,
    date: requestedDate,
    timeZone,
    definitions: {
      morning: '06:00-11:59 local',
      night: '18:00-23:59 local'
    },
    morning,
    night,
    sources: {
      nws: nwsResult.status === 'fulfilled'
        ? 'available' : 'unavailable',
      openMeteo: meteoResult.status === 'fulfilled'
        ? 'available' : 'unavailable'
    },
    generatedAt: new Date().toISOString()
  };
}

async function getWeather(zip, date) {
  validateZip(zip);

  if (typeof date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      Number.isNaN(Date.parse(`${date}T12:00:00Z`)) ||
      new Date(`${date}T12:00:00Z`)
        .toISOString().slice(0, 10) !== date) {
    throw new WeatherError('Invalid calendar date.', 400, 'validation');
  }

  const cached = await getCached(zip, date);
  const now = Math.floor(Date.now() / 1000);

  if (cached && now - cached.savedAt < CACHE_SECONDS) {
    validateDate(date, cached.report.timeZone);

    return {
      ...cached.report,
      cache: 'hit',
      stale: false
    };
  }

  try {
    const location = await lookupZip(zip);
    const point = await getNWSPoint(location);

    validateDate(date, point.timeZone);

    const report = await buildReport(zip, date, location, point);

    await saveCached(zip, date, report);

    return {
      ...report,
      cache: 'miss',
      stale: false
    };

  } catch (error) {
    if (error.status === 502 && cached &&
        now - cached.savedAt <= STALE_SECONDS) {
      validateDate(date, cached.report.timeZone);

      return {
        ...cached.report,
        cache: 'stale',
        stale: true,
        ageSeconds: now - cached.savedAt
      };
    }

    throw error;
  }
}

app.get('/', (req, res) => {
  res.json({
    service: 'weather',
    status: 'healthy',
    endpoint: '/weather?zip=60616&date=YYYY-MM-DD'
  });
});

app.get('/weather', async (req, res) => {
  try {
    const zip = req.query.zip;
    const date = req.query.date;

    const report = await getWeather(zip, date);

    res.json(report);

  } catch (error) {
    const status = error instanceof WeatherError
      ? error.status
      : 500;

    log('weather_error', {
      stage: error.stage || 'internal',
      status
    });

    res.status(status).json({
      error: error.stage || 'internal',
      message: status === 500
        ? 'An internal weather service error occurred.'
        : error.message
    });
  }
});

if (require.main === module) {
  app.listen(PORT, '0.0.0.0', () => {
    log('weather_started', { port: PORT });
  });
}

module.exports = {
  app,
  validateZip,
  validateDate,
  periodName,
  rainCategory,
  snowCategory,
  makePeriod,
  getWeather,
  selectMeteo,
  localParts
};
