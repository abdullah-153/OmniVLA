const {app, BrowserWindow} = require('electron');
const path = require('path');
const fs = require('fs');
const root = path.resolve(__dirname, '..');
const base = 'http://127.0.0.1:8000';
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function waitFor(win, expression) {
  for(let i=0;i<60;i++) { if(await win.webContents.executeJavaScript(expression)) return; await delay(100); }
  throw new Error('Timed out: '+expression);
}
app.whenReady().then(async()=>{
  const errors=[];
  const windows=[];
  try {
    const win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,preload:path.join(root,'console-app','preload.js')}});
    windows.push(win);
    win.webContents.on('console-message',(_e,level,message)=>{if(level===3) errors.push(message)});
    await win.loadURL(base);
    await waitFor(win,`document.getElementById('local-state-label')?.textContent !== 'Checking' && document.getElementById('chat-list')?.children.length > 0`);
    const setup = await win.webContents.executeJavaScript(`(async()=>{ const session=await (await fetch('/api/session')).json(); return {token:!!session.token,manualBudget:!!document.getElementById('max-steps'),profileSection:!!document.getElementById('memory-provenance')}; })()`);
    if(!setup.token || setup.manualBudget || !setup.profileSection) throw new Error('Console setup failed: '+JSON.stringify(setup));
    await win.webContents.executeJavaScript(`fetch('/__fixture/plan',{method:'POST'})`);
    await waitFor(win,`document.querySelector('.plan-card-criteria li')?.textContent.includes('Requested filename') && document.querySelector('.plan-context summary')?.textContent.includes('Personal context supplied')`);
    await win.webContents.executeJavaScript(`fetch('/__fixture/completed',{method:'POST'})`);
    await waitFor(win,`document.querySelector('.completion-evidence summary')?.textContent.includes('visual') && document.querySelector('.completion-evidence p')?.textContent.includes('Filename')`);
    await win.webContents.executeJavaScript(`fetch('/__fixture/memory',{method:'POST'})`);
    await waitFor(win,`document.querySelector('#memory-entities li')?.textContent.includes('Project Atlas') && document.querySelector('#memory-relations li')?.textContent.includes('Sarah Khan')`);
    await win.webContents.executeJavaScript(`fetch('/__fixture/recovery',{method:'POST'})`);
    await waitFor(win,`document.querySelector('.recovery-card')?.textContent.includes('effect uncertain')`);
    await win.webContents.executeJavaScript(`fetch('/__fixture/approval',{method:'POST'}).then(r=>r.json()).then(r=>{window.__fixture=r;})`);
    await waitFor(win,`!document.getElementById('intervention-card').hidden && document.getElementById('intervention-card').dataset.requestId === window.__fixture?.id`);
    await delay(250);
    await fs.promises.writeFile(path.join(root,'scratch','safety-desktop.png'), (await win.webContents.capturePage()).toPNG());
    await win.webContents.executeJavaScript(`document.getElementById('intervention-deny').click()`);
    await waitFor(win,`fetch('/__fixture/result').then(r=>r.json()).then(r=>r.response==='deny')`);
    const mobile=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
    windows.push(mobile);
    await mobile.loadURL(base);
    await waitFor(mobile,`document.getElementById('chat-list')?.children.length > 0`);
    await fs.promises.writeFile(path.join(root,'scratch','safety-mobile.png'), (await mobile.webContents.capturePage()).toPNG());
    const overlay=new BrowserWindow({show:false,width:1280,height:800,transparent:true,frame:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,preload:path.join(root,'overlay-app','preload.js')}});
    windows.push(overlay);
    overlay.webContents.on('console-message',(_e,level,message)=>{if(level===3) errors.push(message)});
    await overlay.loadURL(base+'/overlay/index.html');
    await overlay.webContents.executeJavaScript(`fetch('/__fixture/approval',{method:'POST'}).then(r=>r.json()).then(r=>{window.__fixture=r;})`);
    await waitFor(overlay,`!document.getElementById('hitl-approve').hidden && document.getElementById('hitl-panel').dataset.requestId === window.__fixture?.id`);
    await overlay.webContents.executeJavaScript(`document.getElementById('hitl-approve').click()`);
    await waitFor(overlay,`fetch('/__fixture/result').then(r=>r.json()).then(r=>r.response==='approve')`);
    if(errors.some(e=> /Uncaught|CORS|Refused/.test(e))) throw new Error(errors.join('\n'));
    const result={console:setup,desktopDeny:true,mobileRendered:true,overlayApprove:true,consoleErrors:errors};
    fs.writeFileSync(path.join(root,"scratch","electron-safety-result.json"),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } catch(error) { console.error(error.stack); fs.writeFileSync(path.join(root,"scratch","electron-safety-result.json"),JSON.stringify({error:error.stack,consoleErrors:errors},null,2)); process.exitCode=1; }
  finally { windows.forEach(w=>w.destroy()); app.exit(process.exitCode || 0); }
});
