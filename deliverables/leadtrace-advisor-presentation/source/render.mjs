import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('../../../leadtrace/frontend/node_modules/playwright');

const sourceDir = dirname(fileURLToPath(import.meta.url));
const htmlPath = join(sourceDir, 'presentation.html');
const outputDir = join(sourceDir, '..', 'rendered');

async function sha256(filePath) {
  return createHash('sha256').update(await readFile(filePath)).digest('hex');
}

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1600, height: 900 },
  deviceScaleFactor: 1,
});

try {
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);

  const slides = page.locator('.slide');
  const count = await slides.count();
  if (count !== 12) {
    throw new Error(`Expected 12 slides, found ${count}`);
  }

  const oldFiles = await readdir(outputDir);
  await Promise.all(oldFiles.filter((name) => name.endsWith('.png')).map((name) => rm(join(outputDir, name))));

  for (let index = 0; index < count; index += 1) {
    const slide = slides.nth(index);
    const number = String(index + 1).padStart(2, '0');
    await slide.screenshot({
      path: join(outputDir, `${number}.png`),
      animations: 'disabled',
      caret: 'hide',
    });
  }

  const assetNames = (await readdir(join(sourceDir, 'assets'))).sort();
  const sourceFiles = ['presentation.html', 'styles.css', ...assetNames.map((name) => `assets/${name}`)];
  const renderedFiles = Array.from({ length: count }, (_, index) => `${String(index + 1).padStart(2, '0')}.png`);
  const manifest = {
    format: 1,
    source: Object.fromEntries(await Promise.all(sourceFiles.map(async (name) => [name, await sha256(join(sourceDir, name))]))),
    rendered: Object.fromEntries(await Promise.all(renderedFiles.map(async (name) => [name, await sha256(join(outputDir, name))]))),
  };
  await writeFile(join(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);

  console.log(`Rendered ${count} slides to ${outputDir}`);
} finally {
  await browser.close();
}
