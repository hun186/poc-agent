'use strict';
/* Offline contract for 9002 Editor route landing + layout stability; no API access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'editor_auth_nav.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'editor.css'), 'utf8');
const page = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'editor.html'), 'utf8');
const events = {};
const effects = [];
const styles = {};
const levels = [ {open:true, addEventListener(k,fn){this[k]=fn;}}, {open:true, addEventListener(k,fn){this[k]=fn;}} ];
const group = {
  classList:{contains(k){return k === 'active';}},
  querySelectorAll(k){assert.equal(k,'.nav-level'); return levels;}
};
for (const level of levels) level.closest = () => group;
const panel = {
  classList:{toggle(k,value){effects.push(['panel',k,value]);}},
  querySelectorAll(selector){assert.equal(selector,'.nav-level'); return levels;},
  style:{setProperty(k,v){styles[k]=v;}}
};
const mainNav = {getBoundingClientRect(){return {left:90, width:1020};}};
const rootButtons = ['content','pipeline','system','account'].map(root=>({
  dataset:{navRoot:root}, classList:{toggle(){}}, setAttribute(){},
  getBoundingClientRect(){return {left:root === 'account'?720:450,width:150};}
}));
const menus = rootButtons.map(btn=>({dataset:{navMenu:btn.dataset.navRoot},classList:{toggle(){}}}));
const password = {addEventListener(){}};
const ids = {authPassword:password,navSubPanel:panel,mainNav};
const document = {
  querySelectorAll(selector) {
    if (selector === '[data-nav-root]') return rootButtons;
    if (selector === '[data-nav-menu]') return menus;
    return [];
  },
  querySelector(selector) {
    if (selector.startsWith('[data-nav-root=')) {
      const root = selector.match(/"([^"]+)"/)?.[1];
      return rootButtons.find(b=>b.dataset.navRoot === root) ?? null;
    }
    return null;
  },
  getElementById(id){return ids[id] ?? null;}
};
const state = {user:{role:'data_reader'},activeNavRoot:''};
const window = {
  innerWidth:1200,location:{hash:'#search'},
  addEventListener(type,callback){events[type]=callback;}
};
const context = {
  state, window, document, CSS:{escape:v=>v},
  setStatus:(...args)=>effects.push(['status',...args]),
  switchMainTab:(...args)=>effects.push(['switchMainTab',...args]),
  newDoc:()=>effects.push(['newDoc']),
  SraAuditTools:{bindProgressiveNav:()=>effects.push(['bindProgressiveNav'])}
};
vm.runInNewContext(script, context, {filename:'editor_auth_nav.js'});

function route(hash) {
  effects.length=0;
  window.location.hash=hash;
  events.hashchange();
  return effects.slice();
}
assert.ok(route('#search').some(x=>x[0]==='switchMainTab'&&x[1]==='search'));
assert.ok(route('#account').some(x=>x[0]==='switchMainTab'&&x[1]==='account'));
assert.ok(route('#account-audit').some(x=>x[0]==='switchMainTab'&&x[1]==='account-audit'));
assert.ok(route('#stats').some(x=>x[0]==='switchMainTab'&&x[1]==='stats'&&x[2].source==='document'));
assert.ok(route('#new-document').some(x=>x[0]==='newDoc'));
assert.ok(route('#review').some(x=>x[0]==='status'&&x[1]==='accountStatus'));
assert.ok(!route('#review').some(x=>x[0]==='switchMainTab'&&x[1]==='review'));
state.user.role='superuser';
assert.ok(route('#review').some(x=>x[0]==='switchMainTab'&&x[1]==='review'));
assert.equal(route('#invalid-or-token').length,0);
state.user=null;
assert.equal(route('#account').length,0);
state.user={role:'superuser'};

// Closed first-level flyout is compact, and opening the right-side submenu
// does not mutate the left alignment of top-level items.
context.setActiveNavRoot('account');
assert.ok(levels.every(x=>!x.open), 'close pre-existing submenus on changing roots');
assert.equal(styles['--nav-panel-left'],'352px');
assert.ok(Number.parseInt(styles['--nav-panel-arrow-left'])>=24);
assert.match(css,/nav-subpanel:has\(\.nav-menu\.active \.nav-level\[open\]\)/);
assert.match(css,/width: min\(266px, calc\(100vw - 36px\)\)/);
assert.match(css,/width: min\(740px, calc\(100vw - 36px\)\)/);
assert.doesNotMatch(css,/content:\s*["']右側/);
assert.doesNotMatch(page,/<details class="nav-level" open>/);
assert.match(page,/<details class="nav-level">/);
assert.match(script,/applyEditorEntryRoute\(\);/);
assert.match(script,/window\.addEventListener\('hashchange'/);
assert.match(script,/panel\.style\.setProperty\('--nav-panel-left'/);

// Crossing between child summaries cannot leave two overlapping right panes.
context.bindHeaderNav();
levels[0].open=true;
levels[1].open=true;
levels[1].toggle();
assert.equal(levels[0].open,false);
console.log('SRAF Editor submenu + feature deep-links: PASS');
