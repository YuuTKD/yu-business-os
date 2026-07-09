'use strict';
const path = require('path');
const csv_store = require('./csv_store');

const TARGET_PATH = path.resolve(__dirname, '../../data/master/target_profiles.csv');

function loadAll() { return csv_store.readAll(TARGET_PATH); }
function loadActive(filter = {}) {
  return loadAll().filter(t => {
    if (t.status !== 'active') return false;
    if (filter.target_id && t.target_id !== filter.target_id) return false;
    return true;
  });
}
function findById(id) { return loadAll().find(t => t.target_id === id); }

module.exports = { loadAll, loadActive, findById };
