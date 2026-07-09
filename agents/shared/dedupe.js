'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const DEDUPE_INDEX_PATH = path.resolve(__dirname, '../../data/acquisition/dedupe_index.csv');

function normalizeUrl(url) {
  if (!url) return '';
  try {
    const u = new URL(url);
    return (u.hostname + u.pathname).toLowerCase().replace(/\/+$/, '');
  } catch (_) { return url.toLowerCase().trim(); }
}

function normalizeUsername(username) {
  return (username || '').toLowerCase().replace(/^@/, '').trim();
}

function normalizeDomain(url) {
  if (!url) return '';
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, '');
  } catch (_) { return url.toLowerCase().trim(); }
}

async function loadIndex() {
  const rows = csv_store.readAll(DEDUPE_INDEX_PATH);
  const index = new Set();
  for (const row of rows) {
    if (row.canonical_key) index.add(row.canonical_key);
  }
  return index;
}

async function isDuplicate(row, index) {
  const keys = getKeys(row);
  for (const k of keys) {
    if (k && index.has(k)) return { duplicate: true, key: k };
  }
  return { duplicate: false };
}

function getKeys(row) {
  const keys = [];
  if (row.website_url) keys.push('domain:' + normalizeDomain(row.website_url));
  if (row.account_username) keys.push('username:' + normalizeUsername(row.account_username));
  if (row.account_url) keys.push('url:' + normalizeUrl(row.account_url));
  return keys.filter(Boolean);
}

async function registerToIndex(row, rawId) {
  const keys = getKeys(row);
  for (const k of keys) {
    if (k) {
      csv_store.append(DEDUPE_INDEX_PATH, {
        canonical_key: k, raw_id: rawId,
        registered_at: new Date().toISOString()
      });
    }
  }
}

module.exports = { loadIndex, isDuplicate, getKeys, registerToIndex, normalizeUrl, normalizeDomain, normalizeUsername };
