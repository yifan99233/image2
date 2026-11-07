import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
const dom = new JSDOM('<div id="root"></div>', { url: 'http://test/' });
for (const key of ['window','document','HTMLElement','HTMLInputElement','HTMLTextAreaElement','HTMLSelectElement','Event','CustomEvent','KeyboardEvent']) globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import('react-dom/client');
await build({ entryPoints: ['src/pages/management/CustomerVipDialogs.tsx'], outfile: 'node_modules/.tmp/vip-ui.mjs', bundle: true, platform: 'node', format: 'esm', packages: 'external', jsx: 'automatic', define: { 'import.meta.env': '{"VITE_ADMIN_API_BASE_URL":"http://test"}' } });
const { VipTiersDialog, CustomerVipDialog, customerVipLabel } = await import('../node_modules/.tmp/vip-ui.mjs');
const tiers = [{ id:5, name:'VIP1', site_id:1, discount_rate:.8, is_active:true }];
let root, calls, closes, dones, failRead, failSave;
const settle = async () => act(async () => { await new Promise(r => setTimeout(r, 5)); });
const button = label => [...document.querySelectorAll('button')].find(el => el.textContent === label);
const field = label => [...document.querySelectorAll('label')].find(el => el.textContent.startsWith(label))?.querySelector('input,select,textarea');
async function change(el, value) { assert.ok(el); const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; await act(async () => { Object.getOwnPropertyDescriptor(proto,'value').set.call(el,value); el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input',{ bubbles:true })); }); }
async function click(el) { assert.ok(el); await act(async () => el.click()); await settle(); }
async function render(component, props={}) { await act(async () => root.render(createElement(component,{ ...props, onClose:()=>closes++, afterDone:()=>dones++ }))); await settle(); }
test.beforeEach(() => {
 document.getElementById('root').innerHTML=''; root=createRoot(document.getElementById('root')); calls=[]; closes=0; dones=0; failRead=false; failSave=false;
 globalThis.fetch=async(url,options={})=>{ const method=options.method??'GET'; calls.push({url,method,body:options.body?JSON.parse(options.body):null}); const fail=method==='GET'?failRead:failSave; return new Response(JSON.stringify({code:fail?40001:0,message:fail?'模拟保存失败':'ok',data:method==='GET'?tiers:{id:7}}),{status:fail?400:200}); };
});
test.afterEach(async()=>{ await act(async()=>root.unmount()); });
test('creates tier with eight-tenths multiplier and reason', async()=>{
 await render(VipTiersDialog); await change(field('等级名称'),'长期客户'); await change(field('客户折扣'),'8'); await change(field('变更原因'),'协议折扣'); await click(button('创建等级'));
 assert.deepEqual(calls.find(c=>c.method==='POST').body,{name:'长期客户',discount_rate:.8,is_active:true,reason:'协议折扣'}); assert.equal(dones,1); assert.equal(closes,1);
});
test('assigns VIP and expiry using customer site',async()=>{
 await render(CustomerVipDialog,{user:{id:2,site_id:9,username:'客户'}}); assert.match(calls[0].url,/site_id=9/); await change(field('客户等级'),'5'); await change(field('有效期'),'2099-10-12T18:00'); await change(field('变更原因'),'开通'); await click(button('保存客户 VIP'));
 const saved=calls.find(c=>c.method==='PUT').body; assert.equal(saved.tier_id,5); assert.equal(saved.expires_at,new Date('2099-10-12T18:00').toISOString()); assert.equal(closes,1);
});
test('ordinary customer clears expired membership',async()=>{
 const user={id:2,username:'客户',vip:{tier_id:5,name:'VIP1',discount_rate:.8,is_active:true,expires_at:'2000-01-01T00:00:00Z'}}; assert.match(customerVipLabel(user),/已到期/); await render(CustomerVipDialog,{user}); await change(field('客户等级'),''); await change(field('变更原因'),'取消'); await click(button('保存客户 VIP')); assert.deepEqual(calls.find(c=>c.method==='PUT').body,{tier_id:null,expires_at:null,reason:'取消'});
});
test('failed read blocks save and offers retry',async()=>{
 failRead=true; await render(CustomerVipDialog,{user:{id:2,username:'客户'}}); assert.equal(button('保存客户 VIP').disabled,true); failRead=false; await click(button('重新读取')); assert.equal(button('保存客户 VIP').disabled,false);
});
test('save failure retains form and escape closes',async()=>{
 failSave=true; await render(CustomerVipDialog,{user:{id:2,username:'客户'}}); await change(field('变更原因'),'test'); await click(button('保存客户 VIP')); assert.equal(closes,0); assert.equal(field('变更原因').value,'test'); await act(async()=>document.querySelector('[role="dialog"]').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))); assert.equal(closes,1);
});
