import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { unzipSync } from 'fflate';
import fs from 'node:fs/promises';
const base = process.env.CANVAS_TEST_BASE || 'http://127.0.0.1:5179';
const browser = await chromium.launch({headless:true,channel:process.env.CANVAS_TEST_BROWSER || "chrome"});
const context = await browser.newContext({viewport:{width:1512,height:982}});
const page = await context.newPage();
const errors=[];
page.on('pageerror', e=> errors.push(e.message));
const projects=new Map();
let createdTasks=0;
let tasksComplete=false;
let statusRequests=0;
const quotes=[];
async function until(predicate, message) {
 const deadline=Date.now()+15000;
 while(!predicate()) { if(Date.now()>deadline) throw new Error(message); await new Promise(resolve=>setTimeout(resolve,100)); }
}
const imageBytes=Buffer.from(await page.evaluate(()=>{
 const canvas=document.createElement('canvas');canvas.width=960;canvas.height=640;
 const ctx=canvas.getContext('2d');ctx.fillStyle='#c7d2fe';ctx.fillRect(0,0,960,640);
 ctx.fillStyle='#4338ca';ctx.fillRect(80,80,800,480);ctx.fillStyle='white';ctx.font='48px sans-serif';ctx.fillText('Canvas 960 × 640',240,340);
 return canvas.toDataURL('image/png').split(',')[1];
}),'base64');
// Native generation providers can return a URL without dimension metadata.
const asset={id:1,url:base+'/test-image.png',local_url:base+'/test-image.png',width:null,height:null,size_bytes:imageBytes.length,mime_type:'image/png',source:'generated',sha256:'test'};
const model={id:1,name:'画布测试模型',code:'canvas-test',work_type:'text_to_image',capability_type:'image',max_input_images:4,max_output_images:4,supported_resolutions:[{value:'1024',label:'1K'},{value:'2048',label:'2K'},{value:'4096',label:'4K'}],supported_aspect_ratios:['1:1','16:9','9:16','4:3','3:4','3:2','2:3','21:9'].map(value=>({value,label:value}))};
await context.addInitScript(()=>{
 localStorage.setItem('image2:user-web:access-token','local-test-only');
 localStorage.setItem('image2:user-web:theme','light');
 localStorage.setItem('image2:workspace-mode-initialized:v1:1','1');
});
await context.route('**/*',async route=>{
 const req=route.request(), url=new URL(req.url()), path=url.pathname.replace(/^\/api/,'');
 const ok=data=>route.fulfill({json:{code:0,message:'ok',data}});
 if(path==='/test-image.png') return route.fulfill({body:imageBytes,contentType:'image/png'});
 if(path==='/auth/me') return ok({id:1,username:'canvas-test',email:'canvas@example.test',is_active:true});
 if(path==='/site/config') return route.fulfill({status:503,json:{code:503,message:'use defaults',data:null}});
 if(path==='/credits/balance') return ok({balance:100,total_recharged:100,total_consumed:0});
 if(path==='/team/teams') return ok([]);
 if(path==='/models') return ok([model]);
 if(path==='/models/1/quote') {quotes.push(req.postDataJSON());return ok({credit_cost:2*req.postDataJSON().output_count});}
 if(path==='/canvas/projects' && req.method()==='GET') return ok({items:[...projects.values()].map(({document,...summary})=>summary),has_more:false});
 if(path.startsWith('/canvas/projects/')) {
   const id=path.split('/').at(-1);
   if(req.method()==='PUT') {
     const body=req.postDataJSON();const old=projects.get(id);
     assert.equal(body.revision,old?.revision||0);
     const result={id,title:body.title,document:body.document,revision:(old?.revision||0)+1,created_at:old?.created_at||new Date().toISOString(),updated_at:new Date().toISOString()};projects.set(id,result);return ok(result);
   }
   if(req.method()==='DELETE') {projects.delete(id);return ok(null);}
   return projects.has(id)?ok(projects.get(id)):route.fulfill({status:404,json:{code:404,message:'missing',data:null}});
 }
 if(path==='/image-tasks' && req.method()==='POST') {
   const body=req.postDataJSON();assert.equal(body.model_id,1);assert.equal(body.resolution,'2048');assert.equal(body.aspect_ratio,'16:9');assert.equal(body.quality,'high');assert.equal(body.output_count,1);createdTasks++;
   return ok({id:createdTasks,status:'queued',output_images:[]});
 }
 if(path==='/image-tasks/statuses') { statusRequests++; return ok(req.postDataJSON().task_ids.map(id=>({id,status:tasksComplete?'succeeded':'running',output_images:tasksComplete?[asset]:[]}))); }
 if(path==='/materials') return ok({items:[{id:1,name:'测试素材',asset}],total:1,page:1,page_size:20});
 if(path==='/materials/assets/link') return ok([]);
 if(path==='/materials/folders') return ok([]);
 if(path==='/uploads/images/r2/presign') return route.fulfill({status:400,json:{code:400,message:'multipart test',data:null}});
 if(path==='/uploads/images') return ok({...asset,width:960,height:640,source:'upload'});
 if(path==='/works'||path==='/gallery'||path==='/image-tasks') return ok([]);
 if(url.origin!==base) return route.abort();
 return route.continue();
});
async function selectSetting(frame, label, value) {
 await frame.getByRole('combobox',{name:label,exact:true}).click();
 const target=frame.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:new RegExp(`^${value}$`)});
 // Use a real pointer click so covered or clipped options fail the regression.
 await target.click({timeout:5000});
 assert.equal(await frame.locator('.canvas-image-settings-popover').isVisible(),true,`${label} selection dismissed the settings panel`);
 await frame.locator('.ant-select-dropdown:visible').waitFor({state:'hidden'});
}
async function checkImageSettings(frame) {
 const settingsButton=frame.getByRole('button',{name:/ · .* · 1 张/}).last();
 await settingsButton.click();
 await selectSetting(frame,'分辨率','2K');
 await selectSetting(frame,'画面比例','21:9');
 await selectSetting(frame,'画面比例','16:9');
 await selectSetting(frame,'质量','高');
 const count=frame.getByRole('spinbutton',{name:'生成张数',exact:true});
 await count.fill('2');
 await count.press('Tab');
 await until(()=>quotes.some(quote=>quote.resolution==='2048'&&quote.aspect_ratio==='16:9'&&quote.output_count===2),'Selected settings did not reach the quote request');
 await frame.getByText('预计 4 积分',{exact:true}).waitFor();
 await count.fill('1');
 await count.press('Tab');
 await frame.getByText('预计 2 积分',{exact:true}).waitFor();
 // A click outside still dismisses both the dropdown and its parent panel.
 await frame.getByRole('combobox',{name:'质量',exact:true}).click();
 await frame.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:/^自动$/}).click({trial:true,timeout:5000});
 await page.screenshot({path:'/tmp/image2-canvas-settings.png',animations:'disabled'});
 await frame.getByText('已保存到云端',{exact:true}).click();
 await frame.locator('.canvas-image-settings-popover').waitFor({state:'hidden'});
 await settingsButton.click();
 for(const [label,value] of [['分辨率','2K'],['画面比例','16:9'],['质量','高']]) {
   assert.equal(await frame.getByRole('combobox',{name:label,exact:true}).locator('..').innerText(),value);
 }
 await settingsButton.click();
}
try {
 await page.goto(base+'/create/canvas');
 const frame=page.frameLocator('iframe[title="画布"]');
 await frame.getByRole('button',{name:'新建画布',exact:true}).first().click();
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 await page.screenshot({path:'/tmp/image2-canvas-initial.png'});
 await frame.getByRole('button',{name:'图片',exact:true}).click();
 await frame.locator('[contenteditable="true"]').fill('一只坐在窗边的小猫');
 const initialZoom=frame.getByRole('slider',{name:'放大/缩小画布'});
 for(let step=0;step<34;step++) await initialZoom.press('ArrowLeft');
 assert.equal(await initialZoom.inputValue(),'66');
 await checkImageSettings(frame);
 console.log('PASS image settings at 66% zoom: mouse selection, quote, count and outside dismissal');
 await frame.getByRole('button',{name:'生成',exact:true}).click();
 await until(()=>JSON.stringify([...projects.values()]).includes('image2TaskIds'), 'Submitted task IDs were not saved');
 const originalId=[...projects.keys()][0];
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 const oldStatusRequests=statusRequests;
 await page.reload();
 await frame.locator('article').getByRole('button').first().click();
 await until(()=>statusRequests>oldStatusRequests, 'Reopened canvas did not poll its pending task');
 tasksComplete=true;
 await frame.locator('[data-node-id] img').first().waitFor();
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 await until(()=>projects.get(originalId).document.nodes.some(node=>node.metadata?.naturalWidth===960&&node.metadata?.naturalHeight===640),'Missing image dimensions were not decoded and saved');
 const generated=projects.get(originalId).document.nodes.find(node=>node.metadata?.content);
 assert.ok(generated.width>=200&&generated.height>=150,'Generated image collapsed');
 assert.ok(Math.abs(generated.width/generated.height-1.5)<0.001,'Generated image aspect ratio was lost');
 await page.screenshot({path:'/tmp/image2-canvas-generated.png'});
 assert.equal(createdTasks,1);
 // Reopen the exact broken geometry written by the previous integration.
 const savedImageId=generated.id;
 const savedPosition=structuredClone(generated.position);
 const broken=structuredClone(projects.get(originalId));
 const brokenImage=broken.document.nodes.find(node=>node.id===savedImageId);
 Object.assign(brokenImage,{width:1,height:1});
 Object.assign(brokenImage.metadata,{naturalWidth:0,naturalHeight:0});
 brokenImage.metadata.images?.forEach(image=>Object.assign(image,{naturalWidth:0,naturalHeight:0}));
 projects.set(originalId,broken);
 await page.reload();
 await frame.locator('article').getByRole('button').first().click();
 await until(()=>projects.get(originalId).document.nodes.some(node=>node.id===savedImageId&&node.width>=200&&node.metadata?.naturalWidth===960),'Previously saved 1×1 image was not repaired');
 const repaired=projects.get(originalId).document.nodes.find(node=>node.id===savedImageId);
 assert.deepEqual(repaired.position,savedPosition,'Repair moved the image');
 assert.equal(repaired.metadata.images[0].naturalHeight,640,'Batch image metadata was not repaired');
 assert.equal(createdTasks,1,'Repair resubmitted a billable task');
 await frame.locator(`[data-node-id="${savedImageId}"] img`).waitFor();
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 // A later reload must preserve an intentional user resize.
 const custom=structuredClone(projects.get(originalId));
 Object.assign(custom.document.nodes.find(node=>node.id===savedImageId),{width:480,height:320});
 projects.set(originalId,custom);
 await page.reload();
 await frame.locator('article').getByRole('button').first().click();
 await frame.locator(`[data-node-id="${savedImageId}"] img`).waitFor();
 const dimensions=await frame.locator(`[data-node-id="${savedImageId}"]`).evaluate(node=>({width:parseFloat(node.style.width),height:parseFloat(node.style.height)}));
 assert.deepEqual(dimensions,{width:480,height:320},'Reload reset a user resize');
 console.log('PASS missing dimensions, old 1×1 document repair and custom size preservation');
 await frame.getByRole('button',{name:'资产',exact:true}).click();
 await frame.getByRole('button',{name:'测试素材',exact:true}).click();
 await until(()=>projects.get(originalId).document.nodes.length>=2,'Inserted material was not saved');
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 const savedNodeCount=projects.get(originalId).document.nodes.length;
 assert.ok(savedNodeCount>=2);
 const frameUrl=page.frames().find(f=>f.url().includes('canvas-app')).url();
 await page.getByRole('link',{name:'我的作品',exact:true}).click();
 await page.getByRole('link',{name:'画布',exact:true}).click();
 assert.equal(page.frames().find(f=>f.url().includes('canvas-app')).url(),frameUrl);
 await frame.getByRole('button',{name:'资产',exact:true}).waitFor();
 console.log('PASS task recovery without duplicate submission, materials and menu preservation', savedNodeCount);
 await frame.getByRole('button',{name:'打开画布菜单'}).click();
 await frame.getByRole('menuitem',{name:/撤销/}).click();
 await until(()=>projects.get(originalId).document.nodes.length===savedNodeCount-1,'Undo did not save');
 await frame.getByRole('button',{name:'打开画布菜单'}).click();
 await frame.getByRole('menuitem',{name:/重做/}).click();
 await until(()=>projects.get(originalId).document.nodes.length===savedNodeCount,'Redo did not save');
 await frame.getByRole('button',{name:'打开画布菜单'}).click();
 const downloadPromise=page.waitForEvent('download');
 await frame.getByRole('menuitem',{name:'导出当前画布'}).click();
 const download=await downloadPromise;
 const exportedPath=await download.path();
 const zip=unzipSync(new Uint8Array(await fs.readFile(exportedPath)));
 const exported=JSON.parse(new TextDecoder().decode(zip['projects.json']));
 assert.equal(exported.projects[0].project.nodes.length,savedNodeCount);
 assert.ok(exported.projects[0].files.length>0,'Export did not bundle images');
 await frame.getByRole('button',{name:'打开画布菜单'}).click();
 await frame.getByRole('menuitem',{name:'我的画布'}).click();
 await frame.locator('input[accept="application/zip,.zip"]').setInputFiles({name:'canvas.zip',mimeType:'application/zip',buffer:await fs.readFile(exportedPath)});
 await Promise.race([
   until(()=>projects.size===2,'Imported canvas was not saved'),
   frame.locator('.ant-message-error').waitFor().then(async()=>{ throw new Error(await frame.locator('.ant-message-error').innerText()); }),
 ]);
 const imported=[...projects.values()].find(project=>project.id!==originalId);
 assert.equal(imported.document.nodes.length,savedNodeCount);
 assert.ok(imported.document.nodes.some(node=>node.metadata?.content?.startsWith(base)),'Imported images were not uploaded');
 await frame.getByRole('button',{name:'新建画布',exact:true}).click();
 await until(()=>projects.size===3,'New canvas was not saved');
 assert.equal([...projects.values()].at(-1).document.nodes.length,0,'Switching projects copied the previous canvas');
 console.log('PASS undo/redo, portable export/import and project isolation');
 const textProjectId=[...projects.keys()].at(-1);
 await page.setViewportSize({width:1512,height:720});
 await frame.getByRole('button',{name:'文本',exact:true}).click();
 await frame.locator('[data-node-id]').dblclick();
 await frame.locator('[data-node-id] textarea').fill('给我生成一个猫咪');
 await frame.locator('[data-node-id] textarea').press('Escape');
 await frame.locator('[data-node-id]').hover();
 await frame.getByRole('button',{name:'用文本生图',exact:true}).click();
 await checkImageSettings(frame);
 await page.setViewportSize({width:1512,height:982});
 console.log('PASS config-node image settings in a short viewport');
 await frame.getByRole('button',{name:'开始生成',exact:true}).click();
 await until(()=>projects.get(textProjectId).document.nodes.some(node=>node.type==='image'&&node.metadata?.naturalWidth===960),'Direct text generation did not decode missing dimensions');
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 const textDocument=projects.get(textProjectId).document;
 const outputNode=textDocument.nodes.find(node=>node.type==='image');
 assert.ok(textDocument.connections.some(connection=>connection.toNodeId===outputNode.id),'Generated image lost its source connection');
 assert.ok(outputNode.width>=200&&outputNode.height>=150,'Directly generated image collapsed');
 await frame.getByTitle('定位到节点',{exact:true}).last().click();
 const output=frame.locator(`[data-node-id="${outputNode.id}"]`);
 await output.hover();
 await frame.getByRole('button',{name:'下载图片',exact:true}).waitFor();
 await frame.getByText('已保存到云端',{exact:true}).waitFor();
 const toolbar=frame.getByRole('button',{name:'查看节点信息',exact:true}).locator('..');
 const imageBox=await output.boundingBox(), toolbarBox=await toolbar.boundingBox();
 assert.ok(Math.abs((imageBox.x+imageBox.width/2)-(toolbarBox.x+toolbarBox.width/2))<3,'Image toolbar is not centered on its node');
 assert.ok(toolbarBox.y+toolbarBox.height<imageBox.y,'Image toolbar overlaps its node');
 const zoom=frame.getByRole('slider',{name:'放大/缩小画布'});
 assert.equal(await zoom.inputValue(),'100');
 for(let step=0;step<11;step++) await zoom.press('ArrowLeft');
 await until(()=>Math.abs(projects.get(textProjectId).document.viewport.k-0.89)<0.001,'Zoom was not saved');
 const zoomedBox=await output.boundingBox();
 assert.ok(Math.abs(zoomedBox.width-outputNode.width*0.89)<3,'Image did not scale with canvas zoom');
 await page.screenshot({path:'/tmp/image2-canvas-text-generated.png'});
 console.log('PASS direct text generation, source connections, toolbar positioning and zoom');
 assert.equal(errors.length,0,errors.join('\n'));
 assert.equal(createdTasks,2,'Restoration submitted another billable task');
 console.log('PASS initial cloud canvas',JSON.stringify([...projects.values()].map(p=>({id:p.id,nodes:p.document.nodes.length}))));
} catch (error) { await page.screenshot({path:'/tmp/image2-canvas-failure.png'}); throw error; } finally {await browser.close();}
