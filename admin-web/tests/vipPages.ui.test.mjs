import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement as h } from 'react';
import { MemoryRouter } from 'react-router-dom';
const dom = new JSDOM('<div id="root"></div>', { url: 'http://test/' });
for (const key of ['window','document','HTMLElement','HTMLInputElement','HTMLSelectElement','Event','CustomEvent']) globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import('react-dom/client');
await build({ stdin: { contents: 'export { App } from "./src/App"; export { AuthProvider } from "./src/store/auth";', resolveDir: process.cwd() }, outfile: 'node_modules/.tmp/vip-pages-ui.mjs', bundle: true, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', define: { 'import.meta.env': '{"VITE_ADMIN_API_BASE_URL":"http://test"}' } });
const { App, AuthProvider } = await import('../node_modules/.tmp/vip-pages-ui.mjs');
let root, admin, calls, failUsers;
const tiers = [{id:5,site_id:1,name:'金卡客户',discount_rate:.8,is_active:true}];
const records = Array.from({length:22}, (_, i) => ({id:i+1,site_id:1,username:`客户${i+1}`,email:`test${i}@example.invalid`,vip:i===0?{tier_id:5,...tiers[0],expires_at:null}:null}));
const settle = async () => act(async()=>{await new Promise(r=>setTimeout(r,250));});
const button = label => [...document.querySelectorAll('button')].find(el=>el.textContent===label);
const field = label => [...document.querySelectorAll('label')].find(el=>el.textContent.startsWith(label))?.querySelector('input,select');
async function click(el) { assert.ok(el); await act(async()=>el.click()); await settle(); }
async function change(el,value) { assert.ok(el); await act(async()=>{const proto=el.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value);el.dispatchEvent(new Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}));});await settle(); }
async function render(path,role='super_admin') {admin.role=role;window.localStorage.setItem('image2_admin_token','test');window.localStorage.setItem('image2_admin_user',JSON.stringify(admin));await act(async()=>root.render(h(MemoryRouter,{initialEntries:[path]},h(AuthProvider,null,h(App)))));await settle();}
test.beforeEach(()=>{
 document.getElementById('root').innerHTML='';root=createRoot(document.getElementById('root'));calls=[];failUsers=false;
 admin={id:1,site_id:1,username:'admin',role:'super_admin',is_active:true};window.localStorage.clear();
 globalThis.fetch=async(url)=>{const parsed=new URL(url);calls.push(parsed);let data={};let fail=false;
  if(parsed.pathname.endsWith('/auth/me'))data=admin;
  else if(parsed.pathname.endsWith('/site/content-config'))data={site_name:'测试站'};
  else if(parsed.pathname.endsWith('/vip-tiers'))data=tiers;
  else if(parsed.pathname.endsWith('/users')) {fail=failUsers;const p=parsed.searchParams;let items=records.filter(u=>(p.get('vip_status')!=='active'||u.vip)&&u.username.includes(p.get('keyword')||''));const page=Number(p.get('page_no')),size=Number(p.get('page_size'));data={items:items.slice((page-1)*size,page*size),total:items.length,page,page_size:size};}
  return new Response(JSON.stringify({code:fail?50001:0,message:fail?'客户加载失败':'ok',data}),{status:fail?500:200});
 };
});
test.afterEach(async()=>{await act(async()=>root.unmount());});
test('separate sidebar links open dedicated grade and customer pages',async()=>{
 await render('/vip-tiers');
 assert.equal(document.querySelector('h2').textContent,'VIP 客户等级设置');
 assert.ok(document.querySelector('a[href="/vip-tiers"]'));assert.ok(document.querySelector('a[href="/vip-customers"]'));
 assert.match(document.querySelector('table').textContent,/金卡客户.*8 折/);
 await click(button('编辑等级'));assert.equal(field('等级名称').value,'金卡客户');assert.equal(field('客户折扣').value,'8');
 await click(button('取消'));await click(document.querySelector('nav a[href="/vip-customers"]'));
 assert.equal(document.querySelector('h2').textContent,'VIP 客户管理');assert.ok(button('开通 VIP'));
});
test('customer filtering and searching reset server pagination',async()=>{
 await render('/vip-customers');await click(button('下一页'));
 assert.equal(calls.filter(u=>u.pathname.endsWith('/users')).at(-1).searchParams.get('page_no'),'2');
 await change(field('会员状态'),'active');let params=calls.filter(u=>u.pathname.endsWith('/users')).at(-1).searchParams;assert.equal(params.get('page_no'),'1');assert.equal(params.get('vip_status'),'active');
 assert.equal(document.querySelectorAll('tbody tr').length,1);
 await change(document.querySelector('[aria-label="搜索客户"]'),'不存在');assert.match(document.body.textContent,/没有符合条件的客户/);
});
test('ordinary customers can open membership editor',async()=>{
 await render('/vip-customers');await click(button('开通 VIP'));assert.equal(document.querySelector('[role="dialog"]').getAttribute('aria-label'),'设置客户 VIP');assert.equal(field('客户等级').value,'');
});
test('operators can read but cannot edit grades or customer membership',async()=>{
 await render('/vip-tiers','operator');assert.equal(button('新建等级'),undefined);assert.equal(button('编辑等级'),undefined);
 await click(document.querySelector('nav a[href="/vip-customers"]'));assert.equal(button('开通 VIP'),undefined);assert.equal(button('调整 VIP'),undefined);assert.ok(document.querySelector('table'));
});
test('unauthorized direct route performs no customer or grade reads',async()=>{
 await render('/vip-customers','model_admin');assert.match(document.body.textContent,/无权查看/);assert.equal(calls.filter(u=>u.pathname.endsWith('/users')||u.pathname.endsWith('/vip-tiers')).length,0);assert.equal(document.querySelector('nav a[href="/vip-customers"]'),null);
});
test('failed customer read provides retry and hides stale records',async()=>{
 failUsers=true;await render('/vip-customers');assert.match(document.body.textContent,/客户加载失败/);assert.equal(document.querySelector('table'),null);failUsers=false;await click(button('重试'));assert.ok(document.querySelector('table'));
});
