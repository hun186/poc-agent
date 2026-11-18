'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'excel_global_nav.js'), 'utf8');
class Element {
  constructor(tag, id = '') {
    this.tagName = tag; this.id = id; this.children = []; this.listeners = {};
    this.attributes = {}; this.textContent = ''; this.href = ''; this.className = '';
  }
  appendChild(n) { this.children.push(n); return n; }
  append(...nodes) { nodes.forEach(n => this.appendChild(n)); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  querySelectorAll(selector) {
    if (selector === ':scope > details') return this.children.filter(x => x.tagName === 'details');
    throw Error('unexpected selector: ' + selector);
  }
  querySelector() { return null; }
  contains() { return false; }
}
const whoami = new Element('div', 'whoami');
whoami.textContent = '已登入';
const nav = new Element('nav');
nav.appendChild(whoami);
const editor = new Element('span', 'srafEditorExternalNav');
const document = {
  createElement(tag) { return new Element(tag); },
  querySelectorAll(sel) { return sel === '.global-tree-nav' ? [nav] : []; },
  getElementById(id) { return id === editor.id ? editor : null; },
  addEventListener() {}
};
const window = {
  location: {pathname:'/report-jobs'},
  matchMedia() { return {matches:false}; },
  setTimeout() { throw Error('unexpected timer'); },
  clearTimeout() {}
};
vm.runInNewContext(source, {document, window, WeakMap, Array}, {filename:'excel_global_nav.js'});
assert.equal(nav.children[0], whoami, 'legacy page own identity remains');
const menus = nav.children.filter(n => n.tagName === 'details');
assert.equal(menus.length, 4);
assert.deepEqual(menus.map(x => x.children[0].textContent), ['ES 資料庫','匯入管理','系統管理','帳號安全']);
const links = nav.children.filter(n => n.tagName === 'a');
assert.deepEqual(links.map(x => x.textContent), [
  '代理人資料流程圖', '報告任務進度', '需求任務與執行紀錄', '前往登入 / 編輯器'
]);
assert.equal(links[1].href, '/report-jobs');
assert.equal(links[1].attributes['aria-current'], 'page');
assert.equal(editor.children.length, 3);
assert.deepEqual(editor.children.map(x => x.href), ['/agent-data-flow', '/report-jobs', '/requirement-product']);
assert.ok(editor.children.every(x => x.tagName === 'a'));
assert.deepEqual(editor.children.map(x => x.id), [
  'agentDataFlowBtn', 'reportJobsBtn', 'requirementProductBtn'
]);
assert.equal(menus[1].children[1].children.length, 5);
assert.deepEqual(menus[0].children[1].children.map(a=>a.href), [
  '/editor#search', '/editor#new-document', '/editor#stats'
]);
assert.equal(menus[2].children[1].children[0].href, '/editor#review');
assert.deepEqual(menus[3].children[1].children.map(a=>a.href), [
  '/editor#account', '/editor#account-audit'
]);

assert.ok(nav.children.every(x => x.tagName !== 'script'));
const allLinks = [
  ...links, ...menus.flatMap(x => x.children[1].children)
];
assert.ok(allLinks.every(x => typeof x.href === 'string' && x.href.startsWith('/') && !x.href.startsWith('//')));
console.log('Shared SRAF 9002 navigation: PASS');
