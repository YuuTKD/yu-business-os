'use strict';
const { maskObject, maskString } = require('./secret_guard');

const LEVELS = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };
const currentLevel = LEVELS[process.env.LOG_LEVEL?.toUpperCase() || 'INFO'];

function format(level, msg, meta) {
  const ts = new Date().toISOString();
  const maskedMeta = meta ? maskObject(meta) : undefined;
  const maskedMsg = maskString(String(msg));
  const base = `[${ts}] [${level}] ${maskedMsg}`;
  return maskedMeta ? `${base} ${JSON.stringify(maskedMeta)}` : base;
}

const logger = {
  debug: (msg, meta) => { if (currentLevel <= LEVELS.DEBUG) console.debug(format('DEBUG', msg, meta)); },
  info:  (msg, meta) => { if (currentLevel <= LEVELS.INFO)  console.log(format('INFO',  msg, meta)); },
  warn:  (msg, meta) => { if (currentLevel <= LEVELS.WARN)  console.warn(format('WARN',  msg, meta)); },
  error: (msg, meta) => { if (currentLevel <= LEVELS.ERROR) console.error(format('ERROR', msg, meta)); },
};

module.exports = logger;
