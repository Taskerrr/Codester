// Optional browser check: PLAYWRIGHT_MODULE points to an installed Playwright module.
// Run against an isolated, non-polling test server, never a work instance.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:900}});
    const failures = [];
    page.on('pageerror', error => failures.push(error.message));
    const base = process.env.CODESTER_TEST_URL || 'http://127.0.0.1:8877';
    let tunnelState = 'connected';
    const tunnels = () => ({state:tunnelState, desired:tunnelState !== 'disconnected', tunnels:[{
      id:'1234567890abcdef', name:'Work SSH', ssh_host:'10.15.14.129', local_port:8080,
      remote_host:'127.0.0.1',remote_port:8080,desired:tunnelState !== 'disconnected',state:tunnelState,message:'',
    }]});
    await page.route('**/api/tunnels', route => route.fulfill({json:tunnels()}));
    await page.route('**/api/tunnels/*', async route => {
      tunnelState = route.request().url().endsWith('/disconnect') ? 'disconnected' : 'connecting';
      await route.fulfill({json:tunnels()});
    });
    const container = {id:'test123',name:'web',service:'web',image:'test/web',ports:'0.0.0.0:8080->80/tcp, [::]:8080->80/tcp, 0.0.0.0:9000->9000/tcp',running:true,status:'Up 5 minutes',state:'running',memory_used:134217728,manageable:true};
    await page.route('**/api/docker/containers', route => route.fulfill({json:{
      containers:[container], running:1,total:1,memory_used:134217728,memory_limit:1073741824,
      groups:[{id:'project123',kind:'project',name:'Example app',state:'running',running:1,total:1,active:true,manageable:true,containers:[container]}],
    }}));
    await page.goto(base);
    await page.locator('[data-picker="codex"]').click();
    const options = page.locator('#panel-picker-options button');
    assert.equal(await options.count(),4);
    assert.equal(await page.locator('#panel-picker-options small').count(),0);
    assert.equal(await page.locator('#panel-picker > strong').count(),0);
    await page.locator('#panel-picker-close').click();
    await page.locator('.tunnel-dot').click();
    assert.equal(await page.locator('.tunnel-list-row small').innerText(),'10.15.14.129');
    await page.locator('#tunnels').click();
    await page.waitForFunction(() => document.querySelector('#tunnels').dataset.state === 'disconnected');
    await page.locator('#tunnels').click();
    await page.waitForFunction(() => document.querySelector('#tunnels').dataset.state === 'connecting');
    assert.equal(await page.locator('#tunnels .tunnel-track').evaluate(el => getComputedStyle(el).animationName),'tunnel-spin');
    assert.equal(await page.locator('.tunnel-row-toggle .mini-track').evaluate(el => getComputedStyle(el).animationName),'tunnel-spin');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('#tunnels .tunnel-track').evaluate(el => getComputedStyle(el).animationName),'none');
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.keyboard.press('Escape');
    await page.locator('.deck-buttons [data-app="docker"]').click();
    await page.locator('.docker-group').waitFor();
    assert.equal(await page.locator('.docker-count-pill').count(),0);
    assert.equal(await page.locator('.docker-group-heading .docker-row-ports').innerText(),'8080, 9000');
    assert.equal(await page.locator('.docker-group-heading .docker-row-memory').innerText(),'128 MB');
    assert.equal(await page.locator('.docker-group-action.stop').evaluate(el => getComputedStyle(el).color),
      await page.locator('.docker-group-action.stop').evaluate(el => { const probe=document.createElement('span');probe.style.color='var(--danger)';el.append(probe);const c=getComputedStyle(probe).color;probe.remove();return c; }));
    await page.locator('.docker-project-toggle').click();
    assert.equal(await page.locator('.docker-members li').count(),1);
    fs.mkdirSync('artifacts',{recursive:true});
    await page.screenshot({path:'artifacts/ui-cleanup-wide.png'});
    await page.route('**/api/dashboard/layout', route => route.fulfill({json:{layout:route.request().postDataJSON().apps}}));
    await page.locator('#workspace-home').click();
    await page.locator('[data-picker="codex"]').click();
    await page.locator('[data-replace="docker"]').click();
    await page.locator('.channel.docker:not([hidden]) .docker-group').waitFor();
    const bounds = await page.locator('.docker-group-heading').evaluate(el => ({width:el.clientWidth,scroll:el.scrollWidth}));
    assert(bounds.scroll <= bounds.width);
    await page.screenshot({path:'artifacts/ui-cleanup-home.png'});
    await page.locator('.deck-buttons [data-app="docker"]').click();
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'artifacts/ui-cleanup-mobile.png',fullPage:true});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.goto(`${base}/settings`);
    await page.locator('#update-status').filter({hasText:/native Git checkout/}).waitFor();
    assert(await page.locator('#pull-update').isDisabled());
    assert.deepEqual(failures,[]);
    console.log('PASS: picker, SSH states/reduced motion, Docker rows, mobile overflow, update availability.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
