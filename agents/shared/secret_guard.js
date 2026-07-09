'use strict';
// 環境変数から秘匿値を読み、ログ出力前にマスクする
const MASKED = '[REDACTED]';
const SECRET_PATTERNS = [
  /serpapi[_-]?key/i, /api[_-]?key/i, /secret/i, /token/i, /password/i,
  /credential/i, /auth/i, /private[_-]?key/i
];

function getEnv(key, fallback = null) {
  const val = process.env[key];
  if (val === undefined || val === '') {
    if (fallback !== null) return fallback;
    throw new Error(`環境変数 ${key} が未設定です`);
  }
  return val;
}

function maskValue(val) {
  if (typeof val !== 'string') return val;
  if (val.length <= 4) return MASKED;
  return val.slice(0, 4) + MASKED;
}

function maskObject(obj) {
  if (typeof obj !== 'object' || obj === null) return obj;
  const result = Array.isArray(obj) ? [] : {};
  for (const [k, v] of Object.entries(obj)) {
    const isSensitive = SECRET_PATTERNS.some(p => p.test(k));
    result[k] = isSensitive ? maskValue(String(v)) : (typeof v === 'object' ? maskObject(v) : v);
  }
  return result;
}

function maskString(str) {
  if (typeof str !== 'string') return str;
  let result = str;
  // Bearer token形式をマスク
  result = result.replace(/(Bearer\s+)([A-Za-z0-9._-]{8,})/g, '$1' + MASKED);
  return result;
}

module.exports = { getEnv, maskValue, maskObject, maskString, MASKED };
