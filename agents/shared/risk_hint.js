'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const EXCLUSION_RULES_PATH = path.resolve(__dirname, '../../data/master/exclusion_rules.csv');

// 5分類: exclude / risk_high / keep_as_partner / keep_as_referral / keep_as_research
function loadRules() {
  return csv_store.readAll(EXCLUSION_RULES_PATH).filter(r => r.status === 'active');
}

function matchesRule(row, rule) {
  const text = [
    row.post_text, row.profile_text, row.company_name,
    row.account_name, row.business_category_hint, row.detected_need
  ].join(' ').toLowerCase();

  const keywords = (rule.keywords || '').split('|').map(k => k.trim().toLowerCase()).filter(Boolean);
  return keywords.some(k => k && text.includes(k));
}

function applyRiskHints(row) {
  const rules = loadRules();
  const applicable = rules.filter(rule => {
    if (rule.scope === 'global') return true;
    if (rule.scope === 'business' && rule.business_id === row.business_id) return true;
    if (rule.scope === 'offer' && rule.offer_id === row.offer_id) return true;
    if (rule.scope === 'target' && rule.target_id === row.target_id) return true;
    return false;
  });

  // 優先度: target > offer > business > global
  const scopePriority = { target: 0, offer: 1, business: 2, global: 3 };
  const sorted = [...applicable].sort((a, b) =>
    (scopePriority[a.scope] ?? 9) - (scopePriority[b.scope] ?? 9)
  );

  for (const rule of sorted) {
    if (matchesRule(row, rule)) {
      const hint = rule.action || 'exclude';
      logger.debug(`risk_hint: rule ${rule.rule_id} → ${hint}`, { raw_id: row.raw_id });
      return { hint, rule_id: rule.rule_id, reason: rule.reason };
    }
  }
  return { hint: 'none', rule_id: '', reason: '' };
}

module.exports = { applyRiskHints };
