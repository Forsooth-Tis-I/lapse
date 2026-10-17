import { chromium, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomInt, randomUUID } from 'node:crypto';

const root = new URL('../../', import.meta.url).pathname;
const base = process.env.WEB_URL || 'http://localhost:5174';
const api = process.env.API_URL || 'http://localhost:8020';
const uid = 'demo';
const plans = await (await fetch(`${api}/api/plans`)).json();
const plan = plans.filter(plan => plan.old_root === 'phone_old').sort((a,b) => b.created_at.localeCompare(a.created_at))[0];
const step = plan?.steps.find(step => step.status === 'approved');
if (!step) throw new Error('Run verify-live.mjs first to create and approve the demo plan.');
function python(source, input = '') {
  return execFileSync('uv', ['run', '--extra', 'browser', 'python', '-c', source], {cwd: root, input, encoding: 'utf8'});
}
const screenChange = `wp6-screen-${randomUUID()}`;
const previousScreen = python(`
import json
from lapse.exec.base import redis_client
print(json.dumps(redis_client().get("lapse:screen:demo")))
`);
const browser = await chromium.launch({headless: true});
const page = await browser.newPage({viewport:{width:1920,height:1080}});
try {
  await page.goto(base);
  await expect(page.getByText('5 affected accounts', {exact:true})).toBeVisible();
  await page.getByRole('button', {name:'Fix plan', exact:true}).click();
  python(`
from datetime import UTC, datetime
from lapse.graph.planner import update_change
from lapse.contracts import ChangeStatus, ExecStep
from lapse import events
update_change(${JSON.stringify(uid)}, ${JSON.stringify(step.id)}, status=ChangeStatus.awaiting_otp, note="Staged verification: no executor ran. Testing the OTP relay.")
events.publish(${JSON.stringify(uid)}, "exec", ExecStep(at=datetime.now(UTC), change_id=${JSON.stringify(step.id)}, kind="need_otp", message="Staged verification: enter a test code.").model_dump(mode="json"))
`);
  const input = page.getByLabel(`Code for ${step.account_label}`, {exact:true});
  await expect(input).toBeVisible();
  await page.screenshot({path: new URL('../docs/screenshots/plan-awaiting-otp.png', import.meta.url).pathname});
  const code = String(randomInt(100000, 1000000));
  await input.fill(code);
  await page.getByRole('button', {name:'Submit code', exact:true}).click();
  await expect(input).toHaveValue('');
  await expect(page.getByText('Code submitted. Waiting for the executor to verify it.')).toBeVisible();
  python(`
import sys
from lapse import otp
assert otp.wait(${JSON.stringify(uid)}, ${JSON.stringify(step.id)}, timeout_s=0) == sys.stdin.read()
`, code);
  const trace = await (await fetch(`${api}/api/trace`)).json();
  expect(JSON.stringify(trace)).not.toContain(code);
  await page.getByRole('button', {name:'Agent activity', exact:true}).click();
  const traceResponse = await page.request.get(`${api}/api/stats`);
  expect(traceResponse.ok()).toBe(true);
  const rows = await (await fetch(`${api}/api/trace`)).json();
  const fresh = rows.filter(row => row.tool === 'stats').at(-1);
  await expect(page.locator(`[id="trace-${fresh.id}"]`)).toBeAttached();
  python(`
import asyncio
from playwright.async_api import async_playwright
from lapse.exec.base import StepEmitter
async def capture():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1000, "height": 260})
        await page.set_content('<body style="background:#19211d;color:#e4e9df;font:24px sans-serif;padding:30px"><h1>Staged screenshot delivery check</h1><p>Captured by the real executor screenshot emitter.</p><p>No external account action was performed.</p></body>')
        await StepEmitter("demo", ${JSON.stringify(screenChange)}).screenshot(page, "Staged verification: screenshot transport only.")
        await browser.close()
asyncio.run(capture())
`);
  const screenImage = page.locator('.agent-screen img');
  await expect(screenImage).toBeVisible();
  await expect.poll(() => screenImage.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path: new URL('../docs/screenshots/agent-screen-staged.png', import.meta.url).pathname});
  console.log('Real API OTP consumed once; code absent from trace; exec and trace SSE verified; real screenshot emitter image displayed. Executor states were staged.');
} finally {
  python(`
from datetime import UTC, datetime
from lapse.graph.planner import update_change
from lapse.contracts import ChangeStatus, ExecStep
from lapse import events
update_change(${JSON.stringify(uid)}, ${JSON.stringify(step.id)}, status=ChangeStatus(${JSON.stringify(step.status)}), note=${step.note === null ? '""' : JSON.stringify(step.note)})
events.publish(${JSON.stringify(uid)}, "exec", ExecStep(at=datetime.now(UTC), change_id=${JSON.stringify(step.id)}, kind="progress", message="Staged verification finished; original change state restored.").model_dump(mode="json"))
`);
  python(`
import json, sys
from lapse.exec.base import redis_client, StepEmitter
from lapse.config import ROOT_DIR
previous = json.loads(sys.stdin.read())
client = redis_client()
if previous is None:
    client.delete("lapse:screen:demo")
else:
    client.set("lapse:screen:demo", previous)
StepEmitter("demo", ${JSON.stringify(screenChange)}).emit("screenshot", "Staged verification finished; original screenshot restored.")
(ROOT_DIR / "data" / "screens" / "demo" / ${JSON.stringify(`${screenChange}-1.png`)}).unlink(missing_ok=True)
`, previousScreen);
  await browser.close();
}
