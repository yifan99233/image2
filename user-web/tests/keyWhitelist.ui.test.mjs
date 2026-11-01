import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {JSDOM} from 'jsdom';
import {act,createElement} from 'react';
const dom=new JSDOM('<div id="root"></div>',{url:'http://test/opencode/keys'});
for(const name of ['window','document','HTMLElement','HTMLInputElement','Event','CustomEvent','localStorage']) globalThis[name]=dom.window[name];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {createRoot}=await import('react-dom/client');
await build({entryPoints:['src/pages/opencode/OpenAgentKeysPage.tsx'],outfile:'node_modules/.tmp/key-whitelist-ui.mjs',bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',alias:{'@':new URL('../src',import.meta.url).pathname},define:{'import.meta.env':'{"VITE_API_BASE_URL":"http://test"}'}});
const {OpenAgentKeysPage}=await import('../node_modules/.tmp/key-whitelist-ui.mjs');
globalThis.fetch=async(url)=>new Response(JSON.stringify({code:0,data:String(url).includes('/opencode/keys')?{
 api_base_url:'https://agent.test',groups:[36,37,42].map(id=>({id,name:`分组 ${id}`,platform:'openai'})),items:[],total_used:0,today_used:0
}:{site_name:'测试站点'}}),{headers:{'Content-Type':'application/json'}});
test('create key shows both defaults and the added whitelisted group',async()=>{
 const root=createRoot(document.getElementById('root'));
 try{
  await act(async()=>root.render(createElement(OpenAgentKeysPage)));
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,0));});
  const create=[...document.querySelectorAll('button')].find(button=>button.textContent==='创建 Key');
  assert.ok(create); assert.equal(create.disabled,false);
  await act(async()=>create.click());
  const selector=document.querySelector('[role="dialog"] select') ?? document.querySelector('form select');
  assert.ok(selector);
  assert.deepEqual([...selector.options].map(option=>Number(option.value)),[36,37,42]);
 }finally{await act(async()=>root.unmount());}
});
