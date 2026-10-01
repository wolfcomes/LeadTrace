import { fileURLToPath } from 'node:url';
import { expect,test } from '@playwright/test';
// Standalone synthetic canvas: no source papers or live database.
test('narrow landscape viewport uses the exact canvas rectangle and preserves normalized selection',async({page})=>{
 // Generated locally by the test itself: simple landscape page with a large colored rectangle.
 const pdf=await import('node:child_process').then(({execFileSync})=>execFileSync(process.env.LEADTRACE_PYTHON||fileURLToPath(new URL('../../../.venv/bin/python',import.meta.url)),['-c',"import fitz,sys; d=fitz.open(); p=d.new_page(width=800,height=300); p.draw_rect(fitz.Rect(80,60,400,180),fill=(0,0.8,0)); d.new_page(width=300,height=800); sys.stdout.buffer.write(d.tobytes())"]));
 await page.route('**/synthetic-ui-fixture.pdf',r=>r.fulfill({contentType:'application/pdf',body:pdf}));
 await page.goto('/');
 await page.evaluate(async()=>{
  const vueUrl='/node_modules/.vite/deps/vue.js'; const {createApp,h}=await import(/* @vite-ignore */ vueUrl);
  const canvasUrl='/src/pdf-viewer/PdfReviewCanvas.vue'; const {default:Canvas}=await import(/* @vite-ignore */ canvasUrl);
  const root=document.createElement('div');root.id='synthetic-pdf-host';root.style.width='320px';document.body.replaceChildren(root);
  (window as any).regions=[];
  createApp({render:()=>h(Canvas,{pdfUrl:'/synthetic-ui-fixture.pdf',pageCount:2,regions:[],selectionMode:true,allowRotation:false,onCreateRegion:(region:any)=>(window as any).regions.push(region)})}).mount(root);
 });
 const surface=page.locator('[data-pdf-page]'),canvas=page.locator('[data-pdf-canvas]');
 await expect(surface).toHaveAttribute('data-selection-mode','true');
 const a=(await surface.boundingBox())!,b=(await canvas.boundingBox())!;
 expect(a.width).toBeCloseTo(b.width,1);expect(a.height).toBeCloseTo(b.height,1);expect(b.width/b.height).toBeCloseTo(800/300,1);
 await page.mouse.move(b.x+b.width*.1,b.y+b.height*.2);await page.mouse.down();await page.mouse.move(b.x+b.width*.5,b.y+b.height*.6,{steps:5});await page.mouse.up();
 const regions=await page.evaluate(()=>(window as any).regions);
 expect(regions).toHaveLength(1);expect(regions[0].pageNumber).toBe(1);
 for(const [key,val] of Object.entries({x0:.1,y0:.2,x1:.5,y1:.6}))expect(regions[0][key]).toBeCloseTo(val,2);
});
