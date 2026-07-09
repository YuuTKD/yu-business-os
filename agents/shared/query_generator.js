'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const QUERY_TEMPLATES_PATH = path.resolve(__dirname, '../../data/master/query_templates.csv');

function loadTemplates() {
  return csv_store.readAll(QUERY_TEMPLATES_PATH).filter(t => t.status === 'active');
}

// テンプレート変数展開: {location} → variables.location
function expandTemplate(template, variables) {
  return template.replace(/\{([^}]+)\}/g, (_, key) => {
    return variables[key] || `[${key}]`;
  });
}

function buildVariables(playbook, business, offer, target) {
  const vars = {};
  if (business) {
    vars.location = (business.location || '').split('・')[0];
    vars.industry = business.business_type || '';
    vars.pain_keyword = (business.pain_keywords || '').split('|')[0];
    vars.intent_keyword = (business.intent_keywords || '').split('|')[0];
  }
  if (offer) {
    vars.event_keyword = (offer.offer_name || '').replace(/[（）]/g, '');
    vars.service = offer.offer_name || '';
    vars.partner_industry = '';
  }
  if (target) {
    vars.industry = (target.industry_keywords || '').split('|')[0] || vars.industry;
    vars.pain_keyword = (target.pain_keywords || '').split('|')[0] || vars.pain_keyword;
    vars.partner_industry = (target.industry_keywords || '').split('|')[0];
    vars.occasion_keyword = (target.intent_keywords || '').split('|')[0];
  }
  return vars;
}

function generateQueries(playbook, business, offer, target) {
  const templates = loadTemplates();
  const variables = buildVariables(playbook, business, offer, target);
  const queryStrategies = (playbook.query_strategy || '').split('|').map(s => s.trim());

  const queries = [];
  for (const strategyId of queryStrategies) {
    const tpl = templates.find(t => t.template_id === strategyId);
    if (!tpl) {
      logger.warn(`query_generator: template_id ${strategyId} が見つかりません`);
      continue;
    }
    const expanded = expandTemplate(tpl.query_template, variables);
    queries.push({
      template_id: strategyId,
      platform: tpl.platform,
      query: expanded,
      intent: tpl.intent,
      priority: parseInt(tpl.priority || '2'),
      language: tpl.status
    });
  }

  // priority昇順（小=高優先）
  return queries.sort((a, b) => a.priority - b.priority);
}

module.exports = { generateQueries, expandTemplate, buildVariables };
