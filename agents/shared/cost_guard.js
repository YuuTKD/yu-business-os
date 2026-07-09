'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const COST_LOG_PATH = path.resolve(__dirname, '../../data/acquisition/provider_cost_log.csv');
const CONFIG_PATH   = path.resolve(__dirname, '../product_match_acquisition/config.json');

function loadConfig() {
  return JSON.parse(require('fs').readFileSync(CONFIG_PATH, 'utf8'));
}

async function checkBudget(playbookId, estimatedCost) {
  const config = loadConfig();
  const monthly_limit = config.MONTHLY_COST_LIMIT || 60;
  const daily_limit   = config.DAILY_FETCH_LIMIT   || 200;

  // playbookごとの制限チェック（初期$0.50/run）
  const pb_limit = 0.50;
  if (estimatedCost > pb_limit) {
    logger.warn(`cost_guard: playbook ${playbookId} の推定コスト $${estimatedCost} が上限 $${pb_limit} を超えます`);
    return { allowed: false, reason: `playbook_cost_limit_exceeded: $${estimatedCost} > $${pb_limit}` };
  }

  // ログから今日のコスト集計（簡易版）
  let todayCost = 0;
  try {
    const rows = await csv_store.readAll(COST_LOG_PATH);
    const today = new Date().toISOString().slice(0, 10);
    for (const row of rows) {
      if ((row.date || '').startsWith(today)) {
        todayCost += parseFloat(row.cost_usd || '0');
      }
    }
  } catch (_) { /* ログ未作成は無視 */ }

  if (todayCost + estimatedCost > monthly_limit / 30) {
    logger.warn(`cost_guard: 日次コスト上限超過 todayCost=$${todayCost}`);
    return { allowed: false, reason: 'daily_cost_limit_exceeded' };
  }

  return { allowed: true };
}

async function logCost(playbookId, provider, costUsd, resultCount) {
  await csv_store.append(COST_LOG_PATH, {
    date: new Date().toISOString(),
    playbook_id: playbookId,
    provider,
    cost_usd: costUsd,
    result_count: resultCount,
    cost_per_result: resultCount > 0 ? (costUsd / resultCount).toFixed(4) : '0'
  });
}

module.exports = { checkBudget, logCost };
