'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const EXCLUSION_PATH = path.resolve(__dirname, '../../data/master/exclusion_rules.csv');

const OFFER_REQUIRED = ['offer_id', 'business_id', 'offer_name', 'target_type', 'status'];
const TARGET_REQUIRED = ['target_id', 'target_name', 'target_type', 'status'];
// exclusion_signals等の「除外リスト」列はカッピング混入チェック対象外
const CUPPING_SKIP_FIELDS = ['exclusion_signals', 'exclusion_keywords', 'keywords', 'reason'];

function hasCuppingMixin(obj) {
  for (const [k, v] of Object.entries(obj)) {
    if (CUPPING_SKIP_FIELDS.includes(k)) continue;
    if (typeof v === 'string' && /カッピング|cupping/i.test(v)) return true;
  }
  return false;
}

function validateOffer(offer) {
  const errors = [];
  for (const field of OFFER_REQUIRED) {
    if (!offer[field]) errors.push(`必須項目 ${field} が空`);
  }
  // tree_beautyの各列にカッピング混入チェック（除外リスト列はスキップ）
  if (offer.business_id === 'tree_beauty') {
    if (hasCuppingMixin(offer)) {
      errors.push('tree_beauty offer にカッピング関連語が混入しています（禁止）');
    }
  }
  // 薬機法フラグ確認（サービス提供型のみ）
  if (offer.business_id === 'tree_beauty' && offer.offer_type === 'service') {
    if (!offer.compliance_flags?.includes('yakkiho_review_required')) {
      errors.push('tree_beauty offer(service) に yakkiho_review_required フラグが必要です');
    }
  }
  // 未確定事業チェック
  const forbidden = ['北谷ステーキ', '東町モーニング'];
  for (const f of forbidden) {
    if (Object.values(offer).join(' ').includes(f)) {
      errors.push(`未確定事業 "${f}" が含まれています（禁止）`);
    }
  }
  return errors;
}

function validateTarget(target) {
  const errors = [];
  for (const field of TARGET_REQUIRED) {
    if (!target[field]) errors.push(`必須項目 ${field} が空`);
  }
  if (target.business_fit?.includes('tree_beauty')) {
    if (hasCuppingMixin(target)) {
      errors.push('tree_beauty target にカッピング関連語が混入しています（禁止）');
    }
  }
  return errors;
}

function validateAll(offers, targets) {
  const results = { passed: 0, failed: 0, errors: [] };
  for (const offer of offers) {
    const errs = validateOffer(offer);
    if (errs.length > 0) {
      results.failed++;
      results.errors.push({ id: offer.offer_id, type: 'offer', errors: errs });
    } else {
      results.passed++;
    }
  }
  for (const target of targets) {
    const errs = validateTarget(target);
    if (errs.length > 0) {
      results.failed++;
      results.errors.push({ id: target.target_id, type: 'target', errors: errs });
    } else {
      results.passed++;
    }
  }
  return results;
}

module.exports = { validateOffer, validateTarget, validateAll };
