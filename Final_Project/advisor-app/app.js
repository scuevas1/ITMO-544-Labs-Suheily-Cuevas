'use strict';

const crypto = require('crypto');
const express = require('express');
const { SSMClient, GetParameterCommand } = require('@aws-sdk/client-ssm');
const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const {
  DynamoDBDocumentClient,
  GetCommand,
  PutCommand,
  UpdateCommand
} = require('@aws-sdk/lib-dynamodb');
const { SNSClient, SubscribeCommand, PublishCommand,
  ListSubscriptionsByTopicCommand } = require('@aws-sdk/client-sns');

const app = express();
const path = require('path');
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.urlencoded({ extended: false, limit: '10kb' }));

const PORT = Number(process.env.PORT || 3000);
const WEATHER_URL = process.env.WEATHER_URL || 'http://localhost:3001';
const GEMINI_API_BASE = process.env.GEMINI_API_BASE ||
  'https://generativelanguage.googleapis.com';
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-2.5-flash';
const KEY_PARAM = process.env.GEMINI_KEY_PARAM ||
  '/itmo-544-final/gemini-api-key';
const KEY_CACHE_MS = Number(process.env.KEY_CACHE_SECONDS || 300) * 1000;
const GEMINI_DAILY_CAP = Number(process.env.GEMINI_DAILY_CAP || 30);
const REPORT_CACHE_SECONDS = Number(process.env.REPORT_CACHE_SECONDS || 600);
const REPORT_TABLE = process.env.REPORT_TABLE_NAME || '';
const COUNTER_TABLE = process.env.COUNTER_TABLE_NAME || '';
const SNS_TOPIC_ARN = process.env.SNS_TOPIC_ARN || '';

const REGION = process.env.AWS_REGION || 'us-east-2';

const ssm = new SSMClient({ region: REGION });
const sns = new SNSClient({ region: REGION });
const db = DynamoDBDocumentClient.from(
  new DynamoDBClient({ region: REGION })
);

let cachedKey = { value: null, at: 0 };
const localReports = new Map();
const visitors = new Map();
const visitorSalt = crypto.randomBytes(32);

function log(event, details = {}) {
  console.log(JSON.stringify({
    ts: new Date().toISOString(),
    event,
    ...details
  }));
}

function escapeHtml(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/[&<>"']/g, c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[c]));
}


function dateWithinWindow(date, timeZone, now = new Date()) {
  if (typeof date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return false;
  }

  const selected = new Date(date + 'T12:00:00Z');

  if (Number.isNaN(selected.getTime()) ||
      selected.toISOString().slice(0, 10) !== date) {
    return false;
  }

  const today = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(now);

  const parts = {};

  for (const part of today) {
    parts[part.type] = part.value;
  }

  const localToday =
    `${parts.year}-${parts.month}-${parts.day}`;

  const start = Date.parse(localToday + 'T00:00:00Z');
  const end = start + 6 * 86400000;
  const requested = Date.parse(date + 'T00:00:00Z');

  return requested >= start && requested <= end;
}


function validateInput(body) {
  const zip = body.zip;
  const date = body.date;
  const gender = body.gender;
  const email = String(body.email || '').trim().toLowerCase();

  if (typeof zip !== 'string' || !/^[0-9]{5}$/.test(zip)) {
    throw new Error(
      'This service covers US locations only. Enter a five-digit US ZIP code.'
    );
  }

  if (typeof date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      Number.isNaN(Date.parse(date + 'T12:00:00Z')) ||
      new Date(date + 'T12:00:00Z').toISOString().slice(0, 10) !== date) {
    throw new Error('Enter a valid calendar date.');
  }

  if (!['menswear', 'womenswear', 'neutral'].includes(gender)) {
    throw new Error('Choose a valid clothing preference.');
  }

  if (email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw new Error('Enter a valid email address.');
  }

  return { zip, date, gender, email };
}

function visitorId(req) {
  return crypto.createHash('sha256')
    .update(visitorSalt)
    .update(req.ip || 'unknown')
    .digest('hex');
}

function allowVisitor(req, action) {
  const day = new Date().toISOString().slice(0, 10);
  const key = `${day}:${visitorId(req)}:${action}`;
  const current = visitors.get(key) || 0;
  const limit = action === 'email' ? 3 : 20;

  if (current >= limit) return false;

  visitors.set(key, current + 1);

  if (visitors.size > 5000) {
    visitors.clear();
  }

  return true;
}

function reportKey(zip, date, gender) {
  const input = JSON.stringify([zip, date, gender]);

  return crypto.createHash('sha256')
    .update(input)
    .digest('hex');
}

async function getSavedReport(key) {
  const now = Math.floor(Date.now() / 1000);

  if (!REPORT_TABLE) {
    const item = localReports.get(key);
    return item && item.expiresAt > now ? item.report : null;
  }

  const result = await db.send(new GetCommand({
    TableName: REPORT_TABLE,
    Key: { pk: key }
  }));

  const item = result.Item;

  return item && item.expiresAt > now ? item.report : null;
}

async function saveReport(key, report) {
  const expiresAt = Math.floor(Date.now() / 1000) +
    REPORT_CACHE_SECONDS;

  if (!REPORT_TABLE) {
    localReports.set(key, { report, expiresAt });
    return;
  }

  await db.send(new PutCommand({
    TableName: REPORT_TABLE,
    Item: { pk: key, report, expiresAt }
  }));
}

async function useGeminiAllowance() {
  if (!COUNTER_TABLE) return false;

  const today = new Date().toISOString().slice(0, 10);
  const now = Math.floor(Date.now() / 1000);

  try {
    await db.send(new UpdateCommand({
      TableName: COUNTER_TABLE,
      Key: { pk: `gemini#${today}` },
      UpdateExpression:
        'SET #count = if_not_exists(#count, :zero) + :one, expiresAt = :ttl',
      ConditionExpression:
        'attribute_not_exists(#count) OR #count < :limit',
      ExpressionAttributeNames: {
        '#count': 'callCount'
      },
      ExpressionAttributeValues: {
        ':zero': 0,
        ':one': 1,
        ':limit': GEMINI_DAILY_CAP,
        ':ttl': now + 172800
      }
    }));

    return true;
  } catch (error) {
    log('gemini_cap_or_counter_error', {
      code: error.name || 'unknown'
    });
    return false;
  }
}

async function getApiKey() {
  if (cachedKey.value &&
      Date.now() - cachedKey.at < KEY_CACHE_MS) {
    return cachedKey.value;
  }

  const result = await ssm.send(new GetParameterCommand({
    Name: KEY_PARAM,
    WithDecryption: true
  }));

  cachedKey = {
    value: result.Parameter.Value,
    at: Date.now()
  };

  return cachedKey.value;
}

function readableMetric(item) {
  if (!item || item.value === null || item.value === undefined) {
    return 'Not available';
  }

  return `${item.value}${item.unit ? ' ' + item.unit : ''}`;
}

function factsForGemini(weather) {
  return {
    date: weather.date,
    morning: {
      temperature: weather.morning.temperature,
      windSpeed: weather.morning.windSpeed,
      visibility: weather.morning.visibility,
      uv: weather.morning.uv,
      humidity: weather.morning.humidity,
      rain: weather.morning.rain,
      snow: weather.morning.snow
    },
    night: {
      temperature: weather.night.temperature,
      windSpeed: weather.night.windSpeed,
      visibility: weather.night.visibility,
      uv: weather.night.uv,
      humidity: weather.night.humidity,
      rain: weather.night.rain,
      snow: weather.night.snow
    }
  };
}

function validAdvice(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return false;
  }

  for (const period of ['morning', 'night']) {
    const advice = data[period];

    if (!advice || typeof advice !== 'object') return false;

    for (const field of ['road', 'dressing', 'accessories']) {
      const value = advice[field];

      if (typeof value !== 'string' ||
          value.trim().length < 3 ||
          value.length > 250 ||
          /[<>\x00-\x08\x0B\x0C\x0E-\x1F]/.test(value)) {
        return false;
      }
    }
  }

  return true;
}

async function askGemini(weather, gender) {
  const key = await getApiKey();

  const prompt = JSON.stringify({
    clothingCategory: gender,
    facts: factsForGemini(weather)
  });

  const instructions =
    'You are a practical weather advisor. Use only the supplied facts. ' +
    'Do not invent measurements or missing values. ' +
    'Return short advice for morning and night. ' +
    'Each period must contain road, dressing and accessories strings. ' +
    'Keep all suggestions practical and inclusive.';

  const schema = {
    type: 'OBJECT',
    properties: {
      morning: {
        type: 'OBJECT',
        properties: {
          road: { type: 'STRING' },
          dressing: { type: 'STRING' },
          accessories: { type: 'STRING' }
        },
        required: ['road', 'dressing', 'accessories']
      },
      night: {
        type: 'OBJECT',
        properties: {
          road: { type: 'STRING' },
          dressing: { type: 'STRING' },
          accessories: { type: 'STRING' }
        },
        required: ['road', 'dressing', 'accessories']
      }
    },
    required: ['morning', 'night']
  };

  const response = await fetch(
    `${GEMINI_API_BASE}/v1beta/models/${encodeURIComponent(GEMINI_MODEL)}:generateContent`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': key
      },
      body: JSON.stringify({
        systemInstruction: {
          parts: [{ text: instructions }]
        },
        contents: [{
          parts: [{ text: prompt }]
        }],
        generationConfig: {
          responseMimeType: 'application/json',
          responseSchema: schema,
          maxOutputTokens: 600,
          temperature: 0.2
        }
      }),
      signal: AbortSignal.timeout(10000)
    }
  );

  if (!response.ok) {
    throw new Error(`gemini_http_${response.status}`);
  }

  const data = await response.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  const text = parts.map(part => part.text || '').join('');

  const advice = JSON.parse(text);

  if (!validAdvice(advice)) {
    throw new Error('invalid_gemini_response');
  }

  return advice;
}

function fallbackPeriod(facts, gender) {
  const low = facts.temperature?.low;
  const high = facts.temperature?.high;
  const temp = typeof low === 'number' && typeof high === 'number'
    ? (low + high) / 2
    : null;

  const rain = facts.rain?.value;
  const snow = facts.snow?.value;
  const wind = facts.windSpeed?.value;
  const visibility = facts.visibility?.value;
  const uv = facts.uv?.value;

  let dressing = 'Check the local temperature before choosing clothing.';

  if (temp !== null) {
    if (temp <= 32) {
      dressing = 'Wear a heavy coat and warm layers.';
    } else if (temp <= 50) {
      dressing = 'Wear a warm jacket and long pants.';
    } else if (temp <= 68) {
      dressing = 'Wear a light jacket or sweater.';
    } else if (temp <= 80) {
      dressing = 'Wear comfortable, light clothing.';
    } else {
      dressing = 'Wear light, breathable clothing.';
    }
  }

  if (gender === 'menswear') {
    dressing += ' Choose suitable menswear.';
  } else if (gender === 'womenswear') {
    dressing += ' Choose suitable womenswear.';
  } else {
    dressing += ' Choose comfortable gender-neutral options.';
  }

  const road = [];

  if (rain === 'Heavy') road.push('Heavy rain may create slippery roads.');
  else if (rain === 'Mild') road.push('Roads may be wet.');

  if (snow === 'Heavy') road.push('Heavy snow may make roads hazardous.');
  else if (snow === 'Mild') road.push('Watch for snowy or slippery roads.');

  if (typeof visibility === 'number' && visibility < 3) {
    road.push('Visibility may be reduced.');
  }

  if (typeof wind === 'number' && wind >= 25) {
    road.push('Use caution in strong winds.');
  }

  if (temp !== null && temp <= 32 &&
      (['Mild', 'Heavy'].includes(rain) || ['Mild', 'Heavy'].includes(snow))) {
    road.push('Icy surfaces are possible.');
  }

  const accessories = [];

  if (rain === 'Heavy' || rain === 'Mild') {
    accessories.push('umbrella');
  }

  if (snow === 'Heavy' || snow === 'Mild' ||
      (temp !== null && temp <= 32)) {
    accessories.push('gloves');
  }

  if (typeof uv === 'number' && uv >= 3) {
    accessories.push('sunscreen');
  }

  if (typeof wind === 'number' && wind >= 25) {
    accessories.push('windproof jacket');
  }

  return {
    road: road.join(' ') ||
      'Check current road conditions before traveling.',
    dressing,
    accessories: accessories.length
      ? `Carry ${accessories.join(', ')}.`
      : 'Carry your usual daily essentials.'
  };
}

function fallbackAdvice(weather, gender) {
  return {
    morning: fallbackPeriod(weather.morning, gender),
    night: fallbackPeriod(weather.night, gender)
  };
}

async function getWeather(zip, date) {
  const url = new URL('/weather', WEATHER_URL);
  url.searchParams.set('zip', zip);
  url.searchParams.set('date', date);

  const response = await fetch(url, {
    signal: AbortSignal.timeout(16000)
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      data.message || 'Weather data is unavailable.'
    );
  }

  const weather = await response.json();

  if (!weather.morning || !weather.night) {
    throw new Error('Incomplete weather response.');
  }

  return weather;
}


async function getReport(input) {
  const key = reportKey(input.zip, input.date, input.gender);
  const cached = await getSavedReport(key);

  if (cached) {
    if (!dateWithinWindow(input.date, cached.weather.timeZone)) {
      throw new Error(
        'Choose a date from today through six days ahead.'
      );
    }

    return cached;
  }

  const weather = await getWeather(input.zip, input.date);

  if (!dateWithinWindow(input.date, weather.timeZone)) {
    throw new Error(
      'Choose a date from today through six days ahead.'
    );
  }

  let advice;
  let source = 'fallback';

  if (await useGeminiAllowance()) {
    try {
      advice = await askGemini(weather, input.gender);
      source = 'gemini';
    } catch (error) {
      log('gemini_error', {
        reason: error.message.startsWith('gemini_http_')
          ? error.message
          : 'unavailable_or_invalid'
      });
    }
  }

  if (!advice) {
    advice = fallbackAdvice(weather, input.gender);
  }

  const report = {
    weather,
    advice,
    source
  };

  await saveReport(key, report);

  return report;
}


function displayValue(item) {
  if (!item || item.value === null || item.value === undefined) {
    return escapeHtml(`Not available${item?.reason ? ': ' + item.reason : ''}`);
  }
  return escapeHtml(readableMetric(item) +
    (item.source ? ` (${item.source})` : ''));
}

function displayTemperature(item) {
  if (!item || item.low === null || item.high === null) {
    return escapeHtml(`Not available${item?.reason ? ': ' + item.reason : ''}`);
  }
  return escapeHtml(`${item.low}–${item.high} °F` +
    (item.source ? ` (${item.source})` : ''));
}

function reportTable(report) {
  const w = report.weather;
  const a = report.advice;

  const rows = [
    ['Temperature',
      displayTemperature(w.morning.temperature),
      displayTemperature(w.night.temperature)],
    ['Wind speed',
      displayValue(w.morning.windSpeed),
      displayValue(w.night.windSpeed)],
    ['Visibility',
      displayValue(w.morning.visibility),
      displayValue(w.night.visibility)],
    ['UV',
      displayValue(w.morning.uv),
      displayValue(w.night.uv)],
    ['Humidity',
      displayValue(w.morning.humidity),
      displayValue(w.night.humidity)],
    ['Rain',
      displayValue(w.morning.rain),
      displayValue(w.night.rain)],
    ['Snow',
      displayValue(w.morning.snow),
      displayValue(w.night.snow)],
    ['Suggested road conditions',
      escapeHtml(a.morning.road),
      escapeHtml(a.night.road)],
    ['Suggested dressing',
      escapeHtml(a.morning.dressing),
      escapeHtml(a.night.dressing)],
    ['Suggested accessories',
      escapeHtml(a.morning.accessories),
      escapeHtml(a.night.accessories)]
  ];

  return `<table border="1" cellpadding="8">
    <tr><th>Weather information</th><th>Morning</th><th>Night</th></tr>
    ${rows.map(r =>
      `<tr><th>${escapeHtml(r[0])}</th><td>${r[1]}</td><td>${r[2]}</td></tr>`
    ).join('')}
  </table>`;
}

function emailReport(report) {
  const w = report.weather;
  const a = report.advice;

  function periodText(name, facts, advice) {
    return [
      name,
      `Temperature: ${facts.temperature?.low ?? 'N/A'} to ${facts.temperature?.high ?? 'N/A'} F`,
      `Wind: ${readableMetric(facts.windSpeed)}`,
      `Visibility: ${readableMetric(facts.visibility)}`,
      `UV: ${readableMetric(facts.uv)}`,
      `Humidity: ${readableMetric(facts.humidity)}`,
      `Rain: ${readableMetric(facts.rain)}`,
      `Snow: ${readableMetric(facts.snow)}`,
      `Road: ${advice.road}`,
      `Dressing: ${advice.dressing}`,
      `Accessories: ${advice.accessories}`
    ].join('\n');
  }

  return [
    'Weather Advisor Report',
    `Location: ${w.location.city}, ${w.location.state}`,
    `Date: ${w.date}`,
    '',
    periodText('MORNING', w.morning, a.morning),
    '',
    periodText('NIGHT', w.night, a.night),
    '',
    `Advice source: ${report.source}`
  ].join('\n');
}

function recipientHash(email) {
  return crypto.createHash('sha256').update(email).digest('hex');
}

async function subscriptions() {
  const result = [];
  let nextToken;
  do {
    const page = await sns.send(new ListSubscriptionsByTopicCommand({
      TopicArn: SNS_TOPIC_ARN, NextToken: nextToken
    }));
    result.push(...(page.Subscriptions || []));
    nextToken = page.NextToken;
  } while (nextToken);
  return result;
}

async function sendReport(email, report) {
  if (!SNS_TOPIC_ARN) {
    return { status: 'failed', message: 'SNS is not configured.' };
  }

  const recipient = email.trim().toLowerCase();
  const hash = recipientHash(recipient);
  const all = await subscriptions();
  let subscription = all.find(x =>
    x.Protocol === 'email' && x.Endpoint.toLowerCase() === recipient);

  if (!subscription) {
    await sns.send(new SubscribeCommand({
      TopicArn: SNS_TOPIC_ARN,
      Protocol: 'email',
      Endpoint: recipient,
      ReturnSubscriptionArn: true,
      Attributes: {
        FilterPolicy: JSON.stringify({ recipient: [hash] }),
        FilterPolicyScope: 'MessageAttributes'
      }
    }));
    return {
      status: 'pending',
      message: 'Check your inbox and confirm the Amazon SNS subscription, then click Email My Report again.'
    };
  }

  if (!subscription.SubscriptionArn ||
      subscription.SubscriptionArn === 'PendingConfirmation') {
    return {
      status: 'pending',
      message: 'Confirm the SNS subscription in your inbox, then request the report again.'
    };
  }

  if (all.some(x => x.Protocol !== 'email' || !x.Endpoint)) {
    return { status: 'failed', message: 'Unexpected SNS subscription detected.' };
  }

  await sns.send(new PublishCommand({
    TopicArn: SNS_TOPIC_ARN,
    Subject: 'Your Weather Advisor Report',
    Message: emailReport(report),
    MessageAttributes: {
      recipient: { DataType: 'String', StringValue: hash }
    }
  }));
  return { status: 'sent', message: 'Amazon SNS accepted the report for delivery.' };
}

function page(content = '') {
  return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
          content="width=device-width, initial-scale=1.0">

    <title>Weather Advisor</title>

    <link rel="stylesheet" href="/style.css">
</head>

<body>
    <header>
        <h1>Weather Advisor</h1>
        <p>Check the weather and plan your day</p>
    </header>

    <main class="container">

        <section class="form-card">

            <h2>Your Weather Report</h2>

            <p class="last-updated">
                Report Viewed At:
                <span id="lastUpdated"></span>
            </p>

            <p>
                Enter your information below to get
                the weather forecast and recommendations.
            </p>

            <form action="/report" method="POST">

                <div class="form-row">
                    <div class="form-group">
                        <label for="zip">ZIP Code</label>

                        <input
                            type="text"
                            id="zip"
                            name="zip"
                            placeholder="Example: 60616"
                            pattern="[0-9]{5}"
                            maxlength="5"
                            inputmode="numeric"
                            required
                        >
                    </div>

                    <div class="form-group">
                        <label for="date">Select Date</label>

                        <input
                            type="date"
                            id="date"
                            name="date"
                            required
                        >
                    </div>

                </div>

                <div class="form-group">

                    <label for="gender">
                        Gender / Clothing Preference
                    </label>

                    <select
                        id="gender"
                        name="gender"
                        required
                    >
                        <option value="neutral">
                            Gender Neutral
                        </option>

                        <option value="menswear">
                            Menswear
                        </option>

                        <option value="womenswear">
                            Womenswear
                        </option>
                    </select>

                    <small>
                        This is only used to personalize
                        your clothing recommendations.
                    </small>

                </div>

                <div class="form-group">

                    <label for="email">
                        Email Address
                    </label>

                    <input
                        type="email"
                        id="email"
                        name="email"
                        placeholder="example@email.com"
                        required
                    >

                    <small>
                        Enter your email if you want
                        to receive the weather report.
                    </small>

                </div>

                <div class="form-group">
                    <label>
                        <input
                            type="checkbox"
                            id="emailConsent"
                            name="emailConsent"
                            value="yes"
                            style="width: auto;"
                        >
                        I want to receive this weather
                        report by email.
                    </label>
                    <small>
                        Email delivery may require
                        subscription confirmation.
                    </small>
                </div>

                <button
                    type="submit"
                    class="submit-btn"
                >
                    Get Weather Report
                </button>
            </form>
        </section>

        <section class="form-card">

            ${content}

            <h2>About Weather Advisor</h2>

            <p>
                Weather Advisor provides morning and
                night forecasts for your selected
                location and date.
            </p>

            <p>
                The report includes temperature,
                wind speed, visibility, UV index,
                humidity, rain, and snow.
            </p>

            <p>
                It also uses AI to suggest road
                conditions, clothing, and accessories
                based on the weather.
            </p>
        </section>

    </main>

    <script>
        const dateInput = document.getElementById("date");

        function localDateString(date) {
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1)
                .padStart(2, "0");
            const day = String(date.getDate())
                .padStart(2, "0");

            return year + "-" + month + "-" + day;
        }

        const today = new Date();
        const lastDay = new Date(today);
        lastDay.setDate(today.getDate() + 6);

        dateInput.min = localDateString(today);
        dateInput.max = localDateString(lastDay);
        dateInput.value = localDateString(today);
    </script>
    <script>
        const lastUpdated = document.getElementById("lastUpdated");

        if (lastUpdated) {
            lastUpdated.textContent = new Date().toLocaleString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
                hour12: true
             });
         }
    </script>
</body>
</html>
`;
}

function hiddenInput(name, value) {
  return `<input type="hidden" name="${name}" value="${escapeHtml(value)}">`;
}

function renderReport(report, input) {
  const w = report.weather;

  const emailForm = `<form method="POST" action="/email">
    ${hiddenInput('zip', input.zip)}
    ${hiddenInput('date', input.date)}
    ${hiddenInput('gender', input.gender)}
    ${hiddenInput('email', input.email)}
    <p><label><input type="checkbox" name="consent" value="yes" required>
      I request that this report be emailed to the address I entered.
    </label></p>
    <button type="submit">Email My Report</button>
  </form>`;

  return page(`
    <h2>${escapeHtml(w.location.city)}, ${escapeHtml(w.location.state)}</h2>
    <p>Forecast date: ${escapeHtml(w.date)}</p>
    ${reportTable(report)}
    <p>Advice source: ${escapeHtml(report.source)}</p>
    <p>Weather facts: National Weather Service and Open-Meteo. Each reported metric retains its source in the JSON report.</p>
    ${w.stale ? '<p>Warning: Cached weather data may be outdated.</p>' : ''}
    ${emailForm}
  `);
}

app.get('/', (req, res) => {
  res.status(200).send(page());
});

app.post('/report', async (req, res) => {
  try {
    const input = validateInput(req.body);

    if (!allowVisitor(req, 'report')) {
      return res.status(429).send(page(
        '<p>Too many requests. Please try again later.</p>'
      ));
    }

    const report = await getReport(input);

    return res.send(renderReport(report, input));

  } catch (error) {
    log('report_error', { reason: 'validation_or_service_failure' });

    return res.status(400).send(page(
      `<p>${escapeHtml(error.message)}</p>`
    ));
  }
});

app.post('/email', async (req, res) => {
  try {
    const input = validateInput(req.body);

    if (req.body.consent !== 'yes') {
      throw new Error('Email consent is required.');
    }

    if (!allowVisitor(req, 'email')) {
      return res.status(429).send(page(
        '<p>Email request limit reached.</p>'
      ));
    }

    const report = await getReport(input);
    const result = await sendReport(input.email, report);

    res.send(renderReport(report, input).replace('</body>',
      `<p>Email status: ${escapeHtml(result.status)}. ${escapeHtml(result.message)}</p></body>`));

  } catch (error) {
    log('email_error', { reason: 'email_request_failed' });

    res.status(400).send(page(
      `<p>Email request failed: ${escapeHtml(error.message)}</p>`
    ));
  }
});

if (require.main === module) {
  app.listen(PORT, '0.0.0.0', () => {
    log('advisor_started', { port: PORT, model: GEMINI_MODEL });
  });
}

module.exports = {
  app,
  validateInput,
  dateWithinWindow,
  validAdvice,
  fallbackAdvice,
  escapeHtml,
  reportTable,
  emailReport
};
