'use strict';
const path = require('path');
const csv_store = require('./csv_store');

const BUSINESS_PATH = path.resolve(__dirname, '../../data/master/business_profiles.csv');

function loadAll() {
  return csv_store.readAll(BUSINESS_PATH);
}

function loadActive(filter = {}) {
  return loadAll().filter(b => {
    if (b.status !== 'active') return false;
    if (filter.business_id && b.business_id !== filter.business_id) return false;
    return true;
  });
}

function findById(id) {
  return loadAll().find(b => b.business_id === id);
}

module.exports = { loadAll, loadActive, findById };
