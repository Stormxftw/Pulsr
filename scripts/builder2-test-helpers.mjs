// Shared adapters: preserve legacy behavior assertions under the three-step UX.
export const defaultDefinition = {pulse:1,title:'My pulse',icon:'hermes',feeds:{main:{kind:'hermes.activity',params:{scope:'profile'},every:'30s'}},display:[{type:'bar',value:'main.tool_calls_10m',label:'Tool calls',min:0,max:'auto'}]};
export const pause = page => page.waitForTimeout(650);
export async function selectField(page, pointer, value) {
  const control = page.locator(`[data-field="${pointer}"]`).locator('input,textarea,[role=combobox]').first();
  if (await control.evaluate(e=>e.tagName==='SELECT')) return control.selectOption(value);
  await control.click();
  const labels = {fixed:'Fixed',auto:'Auto',metric:'Out of another value',usual:'Compared to usual',up:'Higher is worse',down:'Lower is worse','1h':'1 hour','6h':'6 hours','24h':'1 day','7d':'7 days'};
  await page.getByRole('option',{name:labels[value] || value,exact:true}).click();
  // Legacy scenarios explicitly confirm the source-type replacement, never approval.
  if(pointer.endsWith('/kind')) {
    const dialog=page.getByRole('alertdialog');
    if(await dialog.isVisible())await dialog.getByRole('button',{name:'Discard changes',exact:true}).click();
  }
}
export function compatibleField(page, pointer) {
  const locator = page.locator(`[data-field="${pointer}"]`).locator('input,textarea,[role=combobox]').first();
  locator.selectOption = value => selectField(page,pointer,value);
  return locator;
}
export async function disclose(page, name) {
  const alias = {'Show definition':'Edit YAML','Data sources':'More source options'};
  if (['Shows','Range','Warnings','Style'].includes(name)) {
    await disclose(page,'Customize pieces');
    await page.getByRole('button',{name,exact:true}).click();
    return;
  }
  const summary = page.locator('.pr-builder summary').filter({hasText:new RegExp('^'+(alias[name] || name)+'$')});
  if (!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
}
export async function advanced(page) {
  await disclose(page,'Customize pieces');
}
export async function applyDefinition(page, definition) {
  await disclose(page,'Edit YAML');
  await page.getByRole('textbox',{name:'Pulse definition',exact:true}).fill(typeof definition==='string'?definition:JSON.stringify(definition));
  await pause(page);await page.getByRole('button',{name:'Apply definition',exact:true}).click();await pause(page);
  await disclose(page,'Customize pieces');
}
export async function authoring(page) {
  await page.getByRole('button',{name:'New pulse',exact:true}).click();await pause(page);
  await page.locator('.pr-b2-template').filter({has:page.getByText('Hermes activity',{exact:true})}).click();await pause(page);
  await page.getByRole('button',{name:'Next',exact:true}).click();await pause(page);
  await applyDefinition(page,defaultDefinition);
}
export async function addPiece(page, type) {
  await disclose(page,'Customize pieces');
  const names={stat:'Big number',spark:'Trend line',rings:'Rings',score:'Change ring',bars:'Bar group',bar:'Bar'};
  await page.getByRole('button',{name:'Add a piece',exact:true}).click();
  await page.locator('.pr-b2-piece-gallery .pr-b2-layout').filter({has:page.getByText(names[type],{exact:true})}).click();await pause(page);
}
export async function previewTools(page, action) {
  await page.getByRole('button',{name:'Preview settings',exact:true}).click();
  await action();await page.keyboard.press('Escape');await pause(page);
}
export async function review(page) {
  const next=page.getByRole('button',{name:'Next',exact:true});
  if(await next.count())await next.click();
  await pause(page);await page.getByRole('button',{name:'Review permissions',exact:true}).click();
  await page.locator('.pr-builder-review .pr-approval').waitFor();
}
