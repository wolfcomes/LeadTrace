import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {expect,test} from '@playwright/test';

test('table evidence renders verified synthetic crops and zooms across pages',async({page})=>{
 const pdf=execFileSync(process.env.LEADTRACE_PYTHON||fileURLToPath(new URL('../../../.venv/bin/python',import.meta.url)),['-c',"import fitz,sys; d=fitz.open(); p=d.new_page(width=600,height=800); p.draw_rect(fitz.Rect(60,80,300,400),color=(0,0.8,0),fill=(0,0.8,0)); p=d.new_page(width=600,height=800); p.draw_rect(fitz.Rect(60,80,300,400),color=(0.8,0,0),fill=(0.8,0,0)); sys.stdout.buffer.write(d.tobytes())"]);
 const sha=createHash('sha256').update(pdf).digest('hex');let fetches=0;
 await page.route('**/api/v2/papers/synthetic-table/source-pdf',r=>{fetches++;return r.fulfill({contentType:'application/pdf',body:pdf});});
 await page.goto('/');
 await page.evaluate(async sha=>{
  const vueUrl='/node_modules/.vite/deps/vue.js';const {createApp,h}=await import(/* @vite-ignore */ vueUrl);
  const componentUrl='/src/review/paper/TableEvidenceImages.vue';const {default:Images}=await import(/* @vite-ignore */ componentUrl);
  const root=document.createElement('div');root.id='table-evidence-host';root.style.width='700px';document.body.replaceChildren(root);
  createApp({render:()=>h(Images,{paperId:'synthetic-table',sourceSha:sha,pageCount:2,evidence:[2,1].map(p=>({id:`page-${p}`,kind:'table',source_sha256:sha,page_number:p,caption:`Synthetic Table page ${p}`,x0:.1,y0:.1,x1:.5,y1:.5}))})}).mount(root);
 },sha);
 const images=page.locator('[data-table-evidence-image]');await expect(images).toHaveCount(2);expect(fetches).toBe(0);
 await expect(images.first()).toContainText('page 2');await images.first().locator('summary').click();
 const canvas=images.first().locator('canvas');await expect(canvas).toBeVisible();
 await expect.poll(()=>canvas.evaluate((c:HTMLCanvasElement)=>c.width)).toBeGreaterThan(1);
 await expect.poll(()=>canvas.evaluate((c:HTMLCanvasElement)=>Array.from(c.getContext('2d')!.getImageData(c.width/2,c.height/2,1,1).data).slice(0,3))).toEqual([204,0,0]);
 expect((await canvas.boundingBox())!.width).toBeCloseTo(240, 0);
 await page.evaluate(()=>{document.getElementById('table-evidence-host')!.style.width='180px';});
 await expect.poll(async()=> (await canvas.boundingBox())?.width ?? Infinity).toBeLessThan(180);
 await page.evaluate(()=>{document.getElementById('table-evidence-host')!.style.width='700px';});
 await expect.poll(async()=> (await canvas.boundingBox())?.width ?? 0).toBeCloseTo(240,0);
 await images.nth(1).locator('[data-table-evidence-zoom]').click();const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
 const enlarged=dialog.locator('canvas');await expect(enlarged).toBeVisible();
 await expect.poll(()=>enlarged.evaluate((c:HTMLCanvasElement)=>Array.from(c.getContext('2d')!.getImageData(c.width/2,c.height/2,1,1).data).slice(0,3))).toEqual([0,204,0]);
 await dialog.getByRole('button',{name:/整页查看|Full page/}).click();
 await expect.poll(()=>enlarged.evaluate((c:HTMLCanvasElement)=>c.width/c.height)).toBeCloseTo(.75,2);
 await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);expect(fetches).toBe(1);
});
