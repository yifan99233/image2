import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
const dom = new JSDOM('<div id="root"></div>', {url:'http://test/works'});
for (const key of ['window','document','HTMLElement','HTMLInputElement','Event','CustomEvent']) globalThis[key]=dom.window[key];
Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
// JSDOM has no layout observer; the prompt measures once on mount.
globalThis.ResizeObserver=class { observe() {} disconnect() {} };
const {createRoot}=await import('react-dom/client');
await build({entryPoints:['src/pages/WorksPage.tsx'],outfile:'node_modules/.tmp/works-review.mjs',bundle:true,format:'esm',platform:'node',packages:'external',alias:{'@':process.cwd()+'/src'},define:{'import.meta.env':'{"VITE_API_BASE_URL":"http://test"}'},jsx:'automatic'});
const {WorksPage}=await import('../node_modules/.tmp/works-review.mjs');
const item={id:1,task_id:1,category:'AI 创作',prompt_snapshot:'test',cover_asset:{url:'https://example.invalid/image.png',mime_type:'image/png'},input_assets:[],output_assets:[],created_at:'2026-10-12T00:00:00Z',is_recommended:false,is_collected:false,gallery_review_status:'none'};
let resolvePatch, sent;
globalThis.fetch=async (url, options={})=>{
  let data=[item];
  if(options.method==='PATCH') {
    sent=JSON.parse(options.body);
    await new Promise(r=>resolvePatch=r);
    data={...item,gallery_review_status:sent.is_recommended?'pending':'none'};
  }
  return new Response(JSON.stringify({code:0,data}),{headers:{'Content-Type':'application/json'}});
};
const settle=()=>act(async()=>{await new Promise(r=>setTimeout(r,15));});
const button=(label)=>document.querySelector(`button[aria-label="${label}"]`);
test('submission waits for server, displays pending, and can withdraw without claiming publication',async()=>{
  const root=createRoot(document.getElementById('root'));
  try {
    await act(async()=>root.render(createElement(WorksPage)));
    await settle();
    await act(async()=>button('提交广场审核').click());
    assert.deepEqual(sent,{is_recommended:true});
    assert.equal(button('提交广场审核').disabled,true);
    assert.equal(button('取消公开展示'),null);
    await act(async()=>resolvePatch());
    await settle();
    assert.ok(button('撤回审核'));
    assert.equal(document.querySelector('.work-card__meta').textContent.includes('待审核'),true);
    await act(async()=>button('撤回审核').click());
    assert.deepEqual(sent,{is_recommended:false});
    await act(async()=>resolvePatch());
    await settle();
    assert.ok(button('提交广场审核'));
  } finally { await act(async()=>root.unmount()); }
});
