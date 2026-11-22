'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { validateInput, validAdvice, fallbackAdvice, escapeHtml,
  reportTable, dateWithinWindow } = require('./app');

test('server validation rejects untrusted user inputs', () => {
  const input = {zip:'60616',date:'2026-11-16',gender:'neutral',email:'TEST@EXAMPLE.COM'};
  assert.equal(validateInput(input).email,'test@example.com');
  for(const zip of ['M5V 3L9','SW1A 1AA','1234','123456','<script>']){
    assert.throws(()=>validateInput({...input,zip}));
  }
  assert.throws(()=>validateInput({...input,gender:'custom'}));
  assert.throws(()=>validateInput({...input,email:'bad'}));
});

test('Gemini answer validation accepts structured advice only', () => {
  const fields={road:'Roads could be wet',dressing:'Wear a warm jacket',accessories:'Carry an umbrella'};
  assert.equal(validAdvice({morning:fields,night:fields}),true);
  assert.equal(validAdvice({morning:{...fields,road:'<img>'},night:fields}),false);
  assert.equal(validAdvice({morning:{...fields,road:4},night:fields}),false);
  assert.equal(validAdvice({morning:{...fields,road:'x'.repeat(251)},night:fields}),false);
});

test('escaping removes active markup', () => {
  assert.equal(escapeHtml('<script>'), '&lt;script&gt;');
});

test('fallback gives three advice outputs per period without an LLM', () => {
  const period={temperature:{low:24,high:30},rain:{value:'Mild'},snow:{value:'No'},
    windSpeed:{value:30},visibility:{value:2},uv:{value:0}};
  const advice=fallbackAdvice({morning:period,night:period},'neutral');
  for(const name of ['morning','night']){
    for(const field of ['road','dressing','accessories']) assert.ok(advice[name][field]);
  }
});

test('date boundary uses selected timezone', () => {
  assert.equal(dateWithinWindow('2026-11-16','America/Chicago',new Date('2026-11-16T12:00:00Z')),true);
  assert.equal(dateWithinWindow('2026-11-23','America/Chicago',new Date('2026-11-16T12:00:00Z')),false);
});
