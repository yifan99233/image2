import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {act,createElement} from 'react';
const dom=new JSDOM('<div id="root"></div>',{url:'http://test/agent'});
for(const name of ['window','document','HTMLElement','HTMLInputElement','Event','CustomEvent']) globalThis[name]=dom.window[name];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot}=await import('react-dom/client');
await build({entryPoints:['src/pages/management/CommerceManagementPages.tsx'],outfile:'node_modules/.tmp/key-whitelist-ui.mjs',bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',define:{'import.meta.env':'{"VITE_ADMIN_API_BASE_URL":"http://test"}'}});
const {AgentPage}=await import('../node_modules/.tmp/key-whitelist-ui.mjs');
let config={is_enabled:true,image_billing_enabled:true,base_url:'https://agent.test',admin_api_key_masked:'***',credit_to_agent_rate:100,text_group_id:37,image_group_id:36,key_group_whitelist:[42],user_concurrency:200,user_rpm_limit:0,create_api_key_path:''};
let saved;
globalThis.fetch=async(url,options={})=>{
 let data;
 if(url.endsWith('/agent/groups')) data=[36,37,42,43].map(id=>({id,name:`分组 ${id}`,platform:'openai',is_active:true}));
 else if(options.method==='PATCH'){saved=JSON.parse(options.body);config={...config,...saved};data=config;}
 else data=config;
 return new Response(JSON.stringify({code:0,data}),{headers:{'Content-Type':'application/json'}});
};
const flush=async()=>{await act(async()=>{await new Promise(resolve=>setTimeout(resolve,0));});};
const checkbox=id=>[...document.querySelectorAll('.agent-key-whitelist__option')].find(el=>el.textContent.includes(`分组 ${id}`)).querySelector('input');
test('defaults cannot be unchecked; extras save and survive reload',async()=>{
 let root=createRoot(document.getElementById('root'));
 try{
  await act(async()=>root.render(createElement(AgentPage)));
  await flush();
  for(const id of [36,37]){assert.equal(checkbox(id).checked,true);assert.equal(checkbox(id).disabled,true);}
  assert.equal(checkbox(42).checked,true);
  assert.equal(checkbox(43).checked,false);
  await act(async()=>checkbox(43).click());
  await act(async()=>checkbox(42).click());
  await act(async()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  await flush();
  assert.deepEqual(saved.key_group_whitelist,[43]);
  assert.equal(saved.text_group_id,37);assert.equal(saved.image_group_id,36);
  await act(async()=>root.unmount());
  root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(createElement(AgentPage)));
  await flush();
  assert.equal(checkbox(43).checked,true);assert.equal(checkbox(42).checked,false);
  assert.equal(checkbox(36).checked,true);assert.equal(checkbox(37).checked,true);
 }finally{await act(async()=>root.unmount());}
});
