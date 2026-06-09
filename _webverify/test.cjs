const PW = 'C:\\Users\\jvega\\AppData\\Roaming\\npm\\node_modules\\@playwright\\mcp\\node_modules\\playwright';
const { chromium } = require(PW);
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const page_url = 'file:///' + path.join(ROOT, 'web', 'verify.html').replace(/\\/g, '/');
const bundleText = fs.readFileSync(path.join(__dirname, 'test.warrant'), 'utf8');
const pub = fs.readFileSync(path.join(__dirname, 'pubkey.txt'), 'utf8').trim();
const prose = '# Test\n\nBody.\n';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true,
    args: ['--no-first-run','--no-default-browser-check','--use-angle=swiftshader','--enable-unsafe-swiftshader'] });
  const page = await browser.newPage();
  await page.goto(page_url, { waitUntil: 'domcontentloaded' });

  // 1. valid bundle, correct prose + key
  const ok = await page.evaluate(([t,p,k]) => window.__verify(t,p,k), [bundleText, prose, pub]);
  console.log('VALID case:   ', JSON.stringify(ok));

  // 2. tampered prose
  const badProse = await page.evaluate(([t,p,k]) => window.__verify(t,p,k), [bundleText, 'TAMPERED', pub]);
  console.log('bad prose:    ', JSON.stringify(badProse));

  // 3. tampered ledger entry
  const b = JSON.parse(bundleText); b.ledger_entries.push({ id: 99, kind: 'forged' });
  const badInt = await page.evaluate(([t,p,k]) => window.__verify(t,p,k), [JSON.stringify(b), prose, pub]);
  console.log('forged entry: ', JSON.stringify(badInt));

  // 4. wrong expected key
  const badKey = await page.evaluate(([t,p,k]) => window.__verify(t,p,k), [bundleText, prose, 'AAAA']);
  console.log('wrong key:    ', JSON.stringify(badKey));

  await browser.close();
})();
