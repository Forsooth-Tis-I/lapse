import { chromium, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomInt } from 'node:crypto';

const root = new URL('../../', import.meta.url).pathname;
const base = process.env.WEB_URL || 'http://localhost:5174';
const api = process.env.API_URL || 'http://localhost:8020';
const uid = 'demo';
const plans = await (await fetch(`${api}/api/plans`)).json();
const plan = plans.filter(plan => plan.old_root === 'phone_old').sort((a,b) => b.created_at.localeCompare(a.created_at))[0];
const step = plan?.steps.find(step => step.status === 'approved');
if (!step) throw new Error('Run verify-live.mjs first to create and approve the demo plan.');
function python(source, input = '') {
  return execFileSync('uv', ['run', 'python', '-c', source], {cwd: root, input, encoding: 'utf8'});
}
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
  console.log('Real API OTP relay consumed once; code absent from trace; exec and trace SSE verified. Executor state was staged.');
} finally {
  python(`
from datetime import UTC, datetime
from lapse.graph.planner import update_change
from lapse.contracts import ChangeStatus, ExecStep
from lapse import events
update_change(${JSON.stringify(uid)}, ${JSON.stringify(step.id)}, status=ChangeStatus(${JSON.stringify(step.status)}), note=${step.note === null ? '""' : JSON.stringify(step.note)})
events.publish(${JSON.stringify(uid)}, "exec", ExecStep(at=datetime.now(UTC), change_id=${JSON.stringify(step.id)}, kind="progress", message="Staged verification finished; original change state restored.").model_dump(mode="json"))
`);
  await browser.close();
}
