'use strict';
const path = require('path');
const csv_store = require('./csv_store');

const OFFER_PATH = path.resolve(__dirname, '../../data/master/offer_profiles.csv');

function loadAll() { return csv_store.readAll(OFFER_PATH); }
function loadActive(filter = {}) {
  return loadAll().filter(o => {
    if (o.status !== 'active') return false;
    if (filter.business_id && o.business_id !== filter.business_id) return false;
    if (filter.offer_id && o.offer_id !== filter.offer_id) return false;
    return true;
  });
}
function findById(id) { return loadAll().find(o => o.offer_id === id); }

module.exports = { loadAll, loadActive, findById };
