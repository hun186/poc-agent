'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'sra_api', 'static', 'requirement_product_preview.js'), 'utf8');
const ids = ['authToken','previewProfile','previewMode','previewFile','previewJson','previewFileGroup','previewJsonGroup',
  'previewBtn','previewClearBtn','previewMessage','previewResult','previewSummary','previewRows','previewDiagnostics',
  'loadProfilesBtn','previewProfileSelect'];
function element(tag='') {
  return {tag, value:'', files:[], hidden:false, disabled:false, textContent:'', children:[], events:{},
    addEventListener(kind, fn){this.events[kind] = fn;},
    appendChild(child){this.children.push(child);},
    replaceChildren(...xs){this.children = xs;}};
}
const el = Object.fromEntries(ids.map(x => [x, element()]));
el.previewMode.value = 'file';
class FormData {
  constructor(){this.parts=[];}
  append(name,value,filename){this.parts.push({name,value,filename});}
  get(name){return this.parts.find(p=>p.name===name)?.value;}
}
const document = {getElementById(id){assert.ok(el[id],id);return el[id];},createElement(tag){return element(tag);}};
const handlers={};
const window={addEventListener(kind,fn){handlers[kind]=fn;}};
const calls=[], planned=[];
const sandbox={document,window,FormData,TextEncoder,AbortController,console,
  fetch:async (url,opts) => {
    calls.push({url,opts});
    assert.ok(opts.method === 'POST' || opts.method === 'GET');
    assert.equal(opts.credentials,'omit');
    assert.equal(opts.cache,'no-store');
    assert.equal(opts.redirect,'error');
    assert.equal(opts.headers.Authorization,'Bearer a-secret');
    if (opts.method === 'POST') {
      assert.equal(url, '/v1/requirement-task-previews');
      assert.ok(!Object.keys(opts.headers).some(k=>k.toLowerCase()==='content-type'),'browser owns multipart boundary');
      assert.ok(opts.body instanceof FormData);
    } else {
      assert.equal(url, '/v1/requirement-import-profiles');
      assert.equal(opts.body, undefined);
    }
    assert.ok(planned.length,'unexpected request');
    return planned.shift();
  }
};
vm.runInNewContext(source,sandbox,{filename:'requirement_product_preview.js'});
const fire=(id,kind='click')=>el[id].events[kind]();
const response=(status,body)=>({status,ok:status>=200&&status<300,json:async()=>body});
const result=(profile='pv_1')=>({
  profile:{profile_version_id:profile},source_sha256:'a'.repeat(64),row_count:3,accepted_count:2,rejected_count:1,
  has_errors:true,preview_truncated:false,
  normalized_preview:[{source_row_number:2,external_item_id:'req1',title:'<img src=x onerror=alert(1)>',
    prompt_content:'Agent generated text <script>bad</script>',expires_at:null}],
  errors:[{severity:'error',code:'invalid_input',message:'<script>evil</script>'}],
  warnings:[{severity:'warning',code:'input_warning'}]
});
(async()=>{
  assert.equal(calls.length,0,'no POST on page load');
  await fire('previewBtn');assert.equal(calls.length,0);
  assert.match(el.previewMessage.textContent,/db_operator/);
  el.authToken.value='a-secret';fire('authToken','input');
  await fire('previewBtn');assert.equal(calls.length,0);
  assert.match(el.previewMessage.textContent,/Profile/);
  el.previewProfile.value='pv_1';
  el.previewFile.files=[{name:'not-allowed.exe',size:100}];
  await fire('previewBtn');assert.equal(calls.length,0);
  el.previewFile.files=[{name:'需求.csv',size:1234}];
  planned.push(response(200,result()));
  await fire('previewBtn');
  assert.equal(calls.length,1);
  assert.equal(calls[0].opts.body.get('requirements_json'),undefined);
  assert.deepEqual(JSON.parse(calls[0].opts.body.get('task')),{profile_version_id:'pv_1'});
  assert.equal(calls[0].opts.body.get('file').name,'需求.csv');
  assert.equal(el.previewResult.hidden,false);
  assert.equal(el.previewRows.children[0].children[2].textContent,'<img src=x onerror=alert(1)>');
  assert.match(el.previewDiagnostics.children[0].textContent, /<script>evil<\/script>/);
  assert.equal(el.previewBtn.disabled,false);
  assert.ok(el.previewSummary.children.some(c=>c.textContent==='接受筆數'));
  el.previewMode.value='json';fire('previewMode','change');
  assert.equal(el.previewFileGroup.hidden,true);
  assert.equal(el.previewJsonGroup.hidden,false);
  assert.equal(el.previewResult.hidden,true);
  el.previewJson.value='[{"ITEMNO":"2","TITLE":"測試"}]';
  planned.push(response(200,result()));
  await fire('previewBtn');
  assert.equal(calls.length,2);
  assert.equal(calls[1].opts.body.get('file'),undefined);
  assert.equal(calls[1].opts.body.get('requirements_json'),el.previewJson.value);
  el.previewJson.value='{bad-json}';fire('previewJson','change');
  await fire('previewBtn');
  assert.equal(calls.length,2);
  assert.match(el.previewMessage.textContent,/JSON/);
  el.previewJson.value='[' + '"界"'.repeat(400000) + ']';
  await fire('previewBtn');
  assert.equal(calls.length,2,'over 1 MiB should be rejected locally');
  el.previewJson.value='[]';fire('previewJson','change');
  planned.push(response(403,{detail:'PRIVATE_ERROR_DATA'}));
  await fire('previewBtn');
  assert.match(el.previewMessage.textContent,/db_operator/);
  assert.doesNotMatch(el.previewMessage.textContent,/PRIVATE_ERROR_DATA/);
  // Profile inventory is opt-in; show only enabled profiles with active versions.
  planned.push(response(200, {items:[
    {profile_id:'pr_1',name:'中文 Profile',enabled:true,active_version_id:'pv_active'},
    {profile_id:'pr_2',name:'停用版',enabled:false,active_version_id:'pv_disabled'},
    {profile_id:'pr_3',name:'無核准版本',enabled:true,active_version_id:null}
  ]}));
  await fire('loadProfilesBtn');
  assert.equal(calls.at(-1).url,'/v1/requirement-import-profiles');
  assert.equal(el.previewProfileSelect.children.length,2);
  assert.equal(el.previewProfileSelect.children[1].value,'pv_active');
  assert.match(el.previewProfileSelect.children[1].textContent,/中文 Profile/);
  el.previewProfileSelect.value='pv_active';
  fire('previewProfileSelect','change');
  assert.equal(el.previewProfile.value,'pv_active');
  assert.equal(el.previewResult.hidden,true);

  // A stale response after a bearer switch must not repopulate earlier preview data.
  let resume;
  planned.push(new Promise(resolve=>{resume=resolve;}));
  const pending=fire('previewBtn');
  await new Promise(resolve=>setImmediate(resolve));
  const signal=calls.at(-1).opts.signal;
  el.authToken.value='another-principal';fire('authToken','input');
  assert.equal(signal.aborted,true);
  assert.equal(el.previewProfileSelect.children.length,1);
  assert.equal(el.previewProfile.value,'');
  resume(response(200,result()));
  await pending;
  assert.equal(el.previewResult.hidden,true);
  assert.equal(el.previewRows.children.length,0);
  assert.equal(el.previewBtn.disabled,false);
  assert.equal(typeof handlers.pagehide,'function');
  handlers.pagehide();
  assert.equal(el.authToken.value,'');
  assert.equal(el.previewJson.value,'');
  console.log('Product Requirement preview DOM flow PASS: restricted manual preview, form modes, safe DOM, limits and token fence');
})().catch(e=>{console.error(e);process.exitCode=1;});
