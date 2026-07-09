'use strict';
const path = require('path');
const csv_store = require('./csv_store');
const logger = require('./logger');

const LINE_QUEUE_PATH = path.resolve(__dirname, '../../data/acquisition/downstream_export_log.csv');

// LINE本番送信は禁止。通知キュー（CSV）への記録のみ。
// LINE_NOTIFY_ENABLED=true かつ owner-approved の場合のみ実際の通知を許可（本実装外）。

async function queueNotification(message, meta = {}) {
  const config = JSON.parse(require('fs').readFileSync(
    path.resolve(__dirname, '../product_match_acquisition/config.json'), 'utf8'
  ));
  if (config.LINE_NOTIFY_ENABLED && !config.LINE_NOTIFY_DRY_RUN) {
    logger.warn('line_notify: LINE_NOTIFY_ENABLED=true ですが本番送信は未実装です。キューへの記録のみ行います。');
  }
  logger.info(`line_notify [QUEUE]: ${message.slice(0, 100)}`);
  csv_store.append(LINE_QUEUE_PATH, {
    queued_at: new Date().toISOString(),
    type: 'line_notification',
    message: message.slice(0, 500),
    meta_json: JSON.stringify(meta),
    status: 'queued'
  });
}

module.exports = { queueNotification };
