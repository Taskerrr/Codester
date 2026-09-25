const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:720}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const base = process.env.CODESTER_TEST_URL || 'http://127.0.0.1:8877';
    const now = Date.now() / 1000;
    let weather = {state:'ready',location:'Bristol, England, United Kingdom',units:'celsius',updated:now,
      current:{time:now,temperature:16.4,symbol:'partlycloudy_day'},
      hours:Array.from({length:6},(_,i)=>({time:now+(i+1)*3600,temperature:15-i,symbol:i < 2 ? 'clearsky_day' : 'rain'}))};
    await page.route('**/api/weather', route => route.fulfill({json:weather}));
    await page.goto(base);
    await page.locator('#weather-temperature').filter({hasText:'16°C'}).waitFor();
    assert.equal(await page.locator('.rail-bottom #workspace-home').count(),1);
    const dateBounds = await page.locator('#date').boundingBox();
    const weatherBounds = await page.locator('#weather-toggle').boundingBox();
    assert(weatherBounds.x >= dateBounds.x + dateBounds.width);
    assert(Math.abs((weatherBounds.y + weatherBounds.height/2) - (dateBounds.y + dateBounds.height/2)) < 2);
    assert.equal((await page.locator('#weather-toggle').innerText()).trim(),'16°C');
    assert(Number(await page.locator('#clock').evaluate(el => parseFloat(getComputedStyle(el).fontSize))) > 48);
    await page.locator('#weather-toggle').hover();
    await page.locator('#weather-hours-panel').waitFor();
    assert.equal(await page.locator('#weather-hours li').count(),6);
    const popup = await page.locator('#weather-hours-panel').boundingBox();
    assert(popup.x >= 0 && popup.y + popup.height <= 720);
    fs.mkdirSync('artifacts',{recursive:true});
    await page.screenshot({path:'artifacts/weather-desktop.png'});
    await page.keyboard.press('Escape');
    assert(await page.locator('#weather-hours-panel').isHidden());
    await page.locator('#workspace-home').focus();
    await page.locator('#weather-toggle').focus();
    await page.locator('#weather-hours-panel').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('.deck-buttons [data-app="docker"]').click();
    await page.locator('#workspace-home').click();
    await page.waitForFunction(() => document.querySelector('#workspace-home').getAttribute('aria-pressed') === 'true');
    for (const width of [900,1150,1280,2560]) {
      await page.setViewportSize({width,height:720});
      const fits = await page.locator('.rail-clock').evaluate(el => el.scrollWidth <= el.clientWidth);
      assert(fits, `Clock/date/weather must fit at ${width}px`);
    }
    await page.setViewportSize({width:390,height:844});
    await page.locator('#weather-toggle').click();
    const mobilePopup = await page.locator('#weather-hours-panel').boundingBox();
    assert(mobilePopup.x >= 0 && mobilePopup.x + mobilePopup.width <= 390);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path:'artifacts/weather-mobile.png'});
    weather = {...weather,state:'stale',units:'fahrenheit'};
    await page.reload();
    await page.locator('#weather-temperature').filter({hasText:'62°F'}).waitFor();
    assert.equal(await page.locator('#weather-widget').getAttribute('data-state'),'stale');
    weather = {state:'unavailable',message:'Offline'};
    await page.reload();
    await page.locator('#weather-setup').filter({has:page.locator('svg')}).waitFor();
    assert((await page.locator('#weather-setup').getAttribute('aria-label')).includes('unavailable'));
    assert(await page.locator('#weather-current').isHidden());
    weather = {state:'disabled'};
    await page.reload();
    await page.getByRole('link',{name:'Set up weather'}).waitFor();
    await page.route('**/api/weather/locations', route => route.fulfill({json:{locations:[{location:'Bristol, England, United Kingdom',latitude:51.454,longitude:-2.588}]}}));
    await page.locator('#weather-setup').click();
    await page.locator('#weather-query').fill('Bristol');
    await page.locator('#weather-query').press('Enter');
    await page.locator('#weather-results button').click({timeout:5000}).catch(async error => {
      console.error({errors,search:await page.locator('#weather-search-status').textContent(),settings:await page.locator('#settings-status').textContent()});
      throw error;
    });
    assert(await page.locator('#weather-enabled').isChecked());
    await page.locator('#weather-units').selectOption('fahrenheit');
    // Save only to the isolated test profile.
    await page.locator('#settings-form button[type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('#weather-selected').textContent.includes('Bristol'));
    await page.reload();
    await page.locator('#weather-selected').filter({hasText:'Bristol'}).waitFor();
    assert.equal(await page.locator('#weather-units').inputValue(),'fahrenheit');
    await page.locator('#weather-clear').click();
    assert.equal(await page.locator('#weather-enabled').isChecked(),false);
    assert.deepEqual(errors,[]);
    console.log('PASS: inline weather, larger clock, hover, tap, keyboard, Home, mobile, units, stale/offline, location save.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
