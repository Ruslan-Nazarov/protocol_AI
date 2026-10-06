// Exercise the actual localization bootstrap, including unavailable storage.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../protocol_atlas/web/i18n.js'), 'utf8');
for (const [saved, expected] of [[null, 'en'], ['en', 'en'], ['ru', 'ru'], ['invalid', 'en'], ['throws', 'en']]) {
  const context = vm.createContext({
    localStorage: {getItem() {if (saved === 'throws') throw Error('Unavailable'); return saved;}},
    document: {addEventListener() {}},
    window: {addEventListener() {}},
    MutationObserver: class {disconnect() {} observe() {}},
  });
  vm.runInContext(code, context);
  assert.equal(vm.runInContext('AtlasI18n.language', context), expected);
}
console.log('English default and saved language preferences: pass');
