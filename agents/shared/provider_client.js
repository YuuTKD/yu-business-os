'use strict';
const fs   = require('fs');
const path = require('path');
const https = require('https');
const { getEnv } = require('./secret_guard');
const logger = require('./logger');

const FIXTURES_PATH = path.resolve(__dirname, '../../fixtures/fake_serp_response.json');
const CONFIG_PATH   = path.resolve(__dirname, '../product_match_acquisition/config.json');

function loadConfig() {
  return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
}

// DRY_RUN時はfixtures/のモックを返す
function mockFetch(query, options = {}) {
  logger.info(`provider_client [DRY_RUN]: モック取得 query="${query}"`);
  const fixtures = JSON.parse(fs.readFileSync(FIXTURES_PATH, 'utf8'));
  const maxResults = options.maxResults || 10;
  return {
    provider: 'mock',
    query,
    results: fixtures.results.slice(0, maxResults).map(r => ({ ...r, _query: query })),
    cost_estimate_usd: 0
  };
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`JSON parse error: ${e.message}`)); }
      });
    }).on('error', reject);
  });
}

async function fetchSerpApi(query, options = {}) {
  const apiKey = getEnv('SERPAPI_KEY', null);
  if (!apiKey) throw new Error('SERPAPI_KEY 未設定');
  const maxResults = options.maxResults || 10;
  const params = new URLSearchParams({
    api_key: apiKey,
    engine: 'google',
    q: query,
    hl: options.lang || 'ja',
    gl: 'jp',
    num: String(Math.min(maxResults, 10))
  });
  const url = `https://serpapi.com/search.json?${params}`;
  const data = await httpGet(url);
  const items = (data.organic_results || []).map(r => ({
    title: r.title || '',
    url: r.link || '',
    snippet: r.snippet || '',
    source: 'serpapi'
  }));
  return { provider: 'serpapi', query, results: items, cost_estimate_usd: 0.01 };
}

async function fetchGoogleCSE(query, options = {}) {
  const apiKey = getEnv('GOOGLE_CSE_KEY', null);
  const cx = getEnv('GOOGLE_CSE_CX', null);
  if (!apiKey || !cx) throw new Error('GOOGLE_CSE_KEY または GOOGLE_CSE_CX が未設定');
  const maxResults = Math.min(options.maxResults || 10, 10);
  const params = new URLSearchParams({
    key: apiKey, cx, q: query, num: String(maxResults)
  });
  const url = `https://www.googleapis.com/customsearch/v1?${params}`;
  const data = await httpGet(url);
  const items = (data.items || []).map(r => ({
    title: r.title || '',
    url: r.link || '',
    snippet: r.snippet || '',
    source: 'google_cse'
  }));
  return { provider: 'google_cse', query, results: items, cost_estimate_usd: 0.005 };
}

// 統一インターフェース: fetch(query, options)
async function fetch(query, options = {}) {
  const config = loadConfig();
  const dryRun = options.dryRun !== false && config.DRY_RUN !== false;

  if (dryRun) return mockFetch(query, options);

  const allowed = config.ALLOWED_PROVIDERS || ['serpapi', 'google_cse'];
  const blocked  = config.BLOCKED_PROVIDERS || [];

  const providers = (options.providers || allowed).filter(p => !blocked.includes(p));

  for (const provider of providers) {
    try {
      if (provider === 'serpapi')    return await fetchSerpApi(query, options);
      if (provider === 'google_cse') return await fetchGoogleCSE(query, options);
      logger.warn(`provider_client: 未対応provider ${provider} → スキップ`);
    } catch (err) {
      logger.warn(`provider_client: ${provider} 失敗 → fallback`, { error: err.message });
    }
  }
  throw new Error(`全providerが失敗: ${providers.join(', ')}`);
}

module.exports = { fetch };
