'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const ERROR_LOG_PATH = path.resolve(__dirname, '../../data/acquisition/acquisition_errors.csv');

async function handleError(context, error, options = {}) {
  const { playbookId, sourceId, provider, skipOnError = true } = options;
  logger.error(`error_fallback: ${context}`, {
    playbook_id: playbookId, source_id: sourceId, error: error.message
  });

  try {
    csv_store.append(ERROR_LOG_PATH, {
      occurred_at: new Date().toISOString(),
      context,
      playbook_id: playbookId || '',
      source_id: sourceId || '',
      provider: provider || '',
      error_type: error.name || 'Error',
      error_message: error.message.slice(0, 500),
      action_taken: skipOnError ? 'source_skipped' : 'run_stopped'
    });
  } catch (logErr) {
    logger.warn(`error_fallback: ログ書込失敗 ${logErr.message}`);
  }

  if (skipOnError) {
    return { skipped: true };
  }
  throw error;
}

module.exports = { handleError };
