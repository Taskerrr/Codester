// Run against an isolated template server. All API requests are mocked.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:720}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const rows = Array.from({length:12}, (_, index) => ({
      id:String(index).padStart(16, '0'), name:`Forward ${index}`, ssh_host:index < 4 ? 'work-server' : `server-${index}`,
      ssh_port:22, local_port:8000+index, remote_host:'localhost', remote_port:80,
      state:'disconnected', desired:false, message:'',
    }));
    const calls = [];
    const snapshot = () => ({state:rows.every(row => row.desired) ? 'connected' : rows.some(row => row.desired) ? 'partial' : 'disconnected', tunnels:rows});
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/tunnels') return route.fulfill({json:snapshot()});
      if (path.startsWith('/api/tunnels/')) {
        calls.push(path);
        const parts = path.split('/');
        const selected = parts.length === 5 ? rows.filter(row => row.id === parts[3]) : rows;
        for (const row of selected) {
          row.desired = parts.at(-1) === 'connect';
          row.state = row.desired ? 'connected' : 'disconnected';
        }
        return route.fulfill({json:snapshot()});
      }
      if (path === '/api/dashboard') return route.fulfill({json:{services:{},server_time:Date.now()/1000}});
      if (path === '/api/weather') return route.fulfill({json:{status:'disabled'}});
      if (path === '/api/codex/activity') return route.fulfill({json:{tasks:[]}});
      return route.fulfill({json:{}});
    });
    await page.goto(process.env.CODESTER_TEST_URL || 'http://127.0.0.1:8879');
    await page.locator('.tunnel-dot').first().waitFor();
    assert.equal(await page.locator('.tunnel-dot').count(),9);
    await page.locator('.tunnel-dot').first().click();
    assert.equal(await page.locator('.tunnel-list-row').count(),9);
    const control = page.locator('.tunnel-row-toggle').first();
    await control.click();
    await page.waitForFunction(() => document.querySelector('.tunnel-row-toggle').getAttribute('aria-disabled') === 'false');
    assert.equal(calls.length,4);
    assert(rows.slice(0,4).every(row => row.desired));
    assert(rows.slice(4).every(row => !row.desired));
    assert.equal(await page.locator('.tunnel-list-row small').first().innerText(),'4/4 connected · Ports 8000, 8001, 8002, 8003');
    assert.equal(await control.getAttribute('data-state'),'connected');
    assert.equal(await page.locator('.tunnel-dot').first().evaluate(el => getComputedStyle(el).color),'oklch(0.86 0.27 142)');
    await control.focus();
    await page.keyboard.press('Space');
    await page.waitForFunction(() => document.querySelector('.tunnel-row-toggle').getAttribute('aria-disabled') === 'false');
    assert.equal(calls.length,8);
    assert(rows.every(row => !row.desired));
    for (const viewport of [{width:2560,height:720},{width:1280,height:360},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      await page.locator('.tunnel-dot').first().click();
      const bounds = await page.locator('#tunnel-popover').boundingBox();
      assert(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width + 1 && bounds.y + bounds.height <= viewport.height + 1);
      const dots = await page.locator('#tunnel-dots').evaluate(el => ({width:el.clientWidth, scroll:el.scrollWidth, height:el.clientHeight}));
      assert(dots.scroll <= dots.width && dots.height <= 88);
      assert((await control.boundingBox()).height >= 44);
      await page.keyboard.press('Escape');
    }
    assert.deepEqual(errors,[]);
    console.log('Grouped switches, keyboard control, bright green and wide/short/mobile layouts passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
