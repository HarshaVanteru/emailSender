const { chromium } = require('C:/Users/Harsh/AppData/Local/npm-cache/_npx/420ff84f11983ee5/node_modules/playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = process.cwd();
const artifacts = path.join(root, 'frontend/artifacts/live-readonly');
fs.mkdirSync(artifacts, { recursive: true });
const session = JSON.parse(execFileSync(path.join(root,'backend/myenv/Scripts/python.exe'), ['-c', `import json
from datetime import timedelta
from app.core.database import SessionLocal
from app.features.google_login.user import User
from app.core.security import create_access_token
with SessionLocal() as db:
 user=db.query(User).first()
 if not user: raise RuntimeError('No existing user')
 print(json.dumps({'token':create_access_token({'sub':user.email},timedelta(minutes=10))}))`], {cwd:path.join(root,'backend'),encoding:'utf8'}));
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const report={mode:'Live frontend and API; no mocked responses; locally signed 10-minute session; Google OAuth not exercised',runs:[]};
 try {
  for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:900}});
   const page=await context.newPage();
   const run={width,errors:[],failedRequests:[],api:[],checks:[],blockedWrites:[]};
   page.on('pageerror',e=>run.errors.push(e.message));
   page.on('requestfailed',r=>{if(r.failure()?.errorText!=='net::ERR_ABORTED')run.failedRequests.push({path:new URL(r.url()).pathname,error:r.failure()?.errorText});});
   page.on('response',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))run.api.push({path:new URL(r.url()).pathname,status:r.status()});});
   await context.route('**/api/**',async route=>{
    if(!['GET','HEAD','OPTIONS'].includes(route.request().method())){
     run.blockedWrites.push({method:route.request().method(),path:new URL(route.request().url()).pathname});
     return route.abort('blockedbyclient');
    }
    return route.continue();
   });
   await page.goto('http://localhost:5173');
   await page.getByRole('heading',{name:'Your mail. A clearer view.'}).waitFor();
   run.checks.push('Unauthenticated welcome renders');
   const health=await page.request.get('http://localhost:8000/api/v1/health');
   assert.equal(health.status(),200); run.checks.push('Real API health returns 200');
   await page.evaluate(token=>localStorage.setItem('access_token',token),session.token);
   await page.reload();
   await page.getByRole('button',{name:'Open profile settings'}).waitFor();
   const accounts=await page.evaluate(async()=>{const r=await fetch('/api/v1/accounts',{headers:{Authorization:'Bearer '+localStorage.getItem('access_token')}});return {status:r.status,items:await r.json()};});
   assert.equal(accounts.status,200); assert.ok(Array.isArray(accounts.items));
   run.accounts=accounts.items.map(a=>({id:a.id,connected:a.is_connected,mailboxAccess:a.mailbox_access,modifyAccess:a.modify_access,draftAccess:a.draft_access}));
   run.checks.push('Authenticated profile and accounts load from MySQL');
   await page.getByRole('button',{name:'Open profile settings'}).click();
   await page.getByRole('button',{name:'Close settings'}).waitFor();
   await page.getByRole('button',{name:'Close settings'}).click();
   run.checks.push('Profile settings opens and closes');
   await page.getByRole('navigation',{name:'Workspace',exact:true}).getByRole('button',{name:'Write',exact:true}).click();
   if(width<1024)await page.getByRole('button',{name:'Composer',exact:true}).click();
   await page.getByRole('button',{name:'Send email',exact:true}).waitFor();
   run.checks.push('Writing workspace and composer render');
   await page.getByRole('button',{name:'Dark mode',exact:true}).click();
   assert.equal(await page.getByRole('button',{name:'Dark mode',exact:true}).getAttribute('aria-pressed'),'true');
   run.checks.push('Theme toggle works');
   await page.getByRole('navigation',{name:'Workspace',exact:true}).getByRole('button',{name:'Mail',exact:true}).click();
   for(const account of accounts.items){
    const checks=await page.evaluate(async id=>{const headers={Authorization:'Bearer '+localStorage.getItem('access_token')};const result=[];for(const endpoint of [`accounts/${id}/labels`,`emails?account_id=${id}`,`search?account_id=${id}&q=playwright-live-smoke`]){const r=await fetch('/api/v1/'+endpoint,{headers});const data=await r.json();result.push({endpoint,status:r.status,shape:Array.isArray(data)?'array':Object.keys(data),detail:r.ok?undefined:data.detail});}return result;},account.id);
    run.mailbox=checks;
   }
   await page.screenshot({path:path.join(artifacts,`mail-${width}.png`),mask:[page.locator('header')],fullPage:true});
   run.horizontalOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
   assert.equal(run.horizontalOverflow,false);
   assert.equal(run.errors.length,0);
   assert.equal(run.blockedWrites.length,0);
   run.checks.push('No horizontal overflow or browser exceptions; no write requests');
   report.runs.push(run);
   console.log(JSON.stringify(run));
   await context.close();
  }
 } finally {fs.writeFileSync(path.join(artifacts,'report.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
