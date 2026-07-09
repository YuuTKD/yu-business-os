'use strict';
const path = require('path');
const logger = require('./logger');

const CONFIG_PATH = path.resolve(__dirname, '../product_match_acquisition/config.json');

function loadConfig() {
  return JSON.parse(require('fs').readFileSync(CONFIG_PATH, 'utf8'));
}

function requireApproval(operation, args = {}) {
  const config = loadConfig();
  const ownerApproved = args['--owner-approved'] === true;

  if (operation === 'live_run') {
    if (!config.APPROVED_FOR_LIVE) {
      throw new Error(`human_gate: LIVE実行には config.APPROVED_FOR_LIVE=true が必要です`);
    }
    if (!ownerApproved) {
      throw new Error(`human_gate: LIVE実行には --owner-approved フラグが必要です`);
    }
  }

  if (operation === 'paid_api' && config.REQUIRE_OWNER_APPROVAL_FOR_PAID_API) {
    if (!ownerApproved) {
      throw new Error(`human_gate: 有料API使用には --owner-approved フラグが必要です`);
    }
  }

  if (operation === 'new_offer' && config.REQUIRE_OWNER_APPROVAL_FOR_NEW_OFFER) {
    if (!ownerApproved) {
      throw new Error(`human_gate: 新offer有効化には --owner-approved フラグが必要です`);
    }
  }

  if (operation === 'new_target' && config.REQUIRE_OWNER_APPROVAL_FOR_NEW_TARGET) {
    if (!ownerApproved) {
      throw new Error(`human_gate: 新target有効化には --owner-approved フラグが必要です`);
    }
  }

  logger.info(`human_gate: ${operation} 承認済み`);
  return true;
}

function isDryRun(args = {}) {
  const config = loadConfig();
  const hasLiveFlag = args['--live'] === true;
  const hasDryFlag  = args['--dry-run'] === true;
  if (hasDryFlag) return true;
  if (hasLiveFlag && config.APPROVED_FOR_LIVE) return false;
  return config.DRY_RUN !== false; // デフォルトtrue
}

module.exports = { requireApproval, isDryRun };
