'use strict';
const path = require('path');
const csv_store = require('./csv_store');

const PLAYBOOK_PATH = path.resolve(__dirname, '../../data/master/acquisition_playbooks.csv');

function loadAll() { return csv_store.readAll(PLAYBOOK_PATH); }
function loadActive(filter = {}) {
  return loadAll().filter(pb => {
    if (pb.status !== 'active') return false;
    if (filter.business_id && pb.business_id !== filter.business_id) return false;
    if (filter.playbook_id && pb.playbook_id !== filter.playbook_id) return false;
    return true;
  });
}
function findById(id) { return loadAll().find(pb => pb.playbook_id === id); }

module.exports = { loadAll, loadActive, findById };
