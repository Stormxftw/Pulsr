import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
// Usage: node scripts/capture-builder2-before.mjs <hermes-checkout> [out-dir]
const {chromium} = createRequire(path.join(process.argv[2], 'package.json'))('playwright');
const out = process.argv[3] || 'artifacts/wp13-builder-ux/before';
fs.mkdirSync(out, {recursive:true});
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
  for (const width of [320,480,900,1280]) for (const theme of ['light','dark']) {
    const page = await browser.newPage({viewport:{width:1420,height:1100},reducedMotion:'reduce'});
    await page.goto(`http://127.0.0.1:5351/?mode=builder&builder-baseline=1&width=${width}&theme=${theme}`);
    await page.getByRole('button',{name:'New pulse',exact:true}).click();
    await page.waitForTimeout(1000);
    for (const step of [1,2,3,4]) await page.screenshot({path:`${out}/step-${step}-${width}-${theme}.png`,fullPage:true});
    await page.close();
  }
} finally {await browser.close();}
