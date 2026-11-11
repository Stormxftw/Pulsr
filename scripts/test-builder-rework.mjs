import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
const {chromium} = createRequire(path.join(process.argv[2], 'package.json'))('playwright');
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
  const page = await browser.newPage();
  await page.goto((process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5391') + '/?mode=builder&width=670');
  await page.getByRole('button',{name:'New pulse',exact:true}).click();
  assert.deepEqual(await page.locator('.pr-b2-progress button').allTextContents(), ['1Source','2Design','3Review']);
  assert.equal(await page.getByRole('switch',{name:'Advanced',exact:true}).count(), 0);
  console.log('PASS three-step flow and local disclosures');
} finally {
  await browser.close();
}
