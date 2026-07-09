'use strict';
const fs   = require('fs');
const path = require('path');

// 追記専用。既存列の変更・削除禁止。
function readAll(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const content = fs.readFileSync(filePath, 'utf8').trim();
  if (!content) return [];
  const lines = content.split('\n');
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map(h => h.trim());
  return lines.slice(1).map(line => {
    const vals = parseCsvLine(line);
    const obj = {};
    headers.forEach((h, i) => { obj[h] = vals[i] || ''; });
    return obj;
  });
}

function getHeaders(filePath) {
  if (!fs.existsSync(filePath)) return [];
  const content = fs.readFileSync(filePath, 'utf8');
  const firstLine = content.split('\n')[0];
  return firstLine ? firstLine.split(',').map(h => h.trim()) : [];
}

function append(filePath, row) {
  const headers = getHeaders(filePath);
  if (headers.length === 0) throw new Error(`csv_store.append: ヘッダーなし ${filePath}`);
  const vals = headers.map(h => escapeCsv(row[h] !== undefined ? String(row[h]) : ''));
  fs.appendFileSync(filePath, '\n' + vals.join(','), 'utf8');
}

function appendMany(filePath, rows) {
  for (const row of rows) append(filePath, row);
}

function escapeCsv(val) {
  if (val.includes(',') || val.includes('"') || val.includes('\n')) {
    return '"' + val.replace(/"/g, '""') + '"';
  }
  return val;
}

function parseCsvLine(line) {
  const result = [];
  let cur = '', inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"' && line[i+1] === '"') { cur += '"'; i++; }
      else if (ch === '"') { inQuote = false; }
      else cur += ch;
    } else {
      if (ch === '"') { inQuote = true; }
      else if (ch === ',') { result.push(cur); cur = ''; }
      else cur += ch;
    }
  }
  result.push(cur);
  return result;
}

module.exports = { readAll, getHeaders, append, appendMany };
