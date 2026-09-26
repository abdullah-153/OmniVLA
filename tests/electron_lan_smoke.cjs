const {app,BrowserWindow}=require('electron');
const fs=require('fs');const path=require('path');
const out=path.resolve(__dirname,'..','scratch','lan-pairing-result.json');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFor(w,js){for(let i=0;i<70;i++){if(await w.webContents.executeJavaScript(js))return;await delay(100)}throw new Error('Timed out: '+js)}
app.whenReady().then(async()=>{let w;try{
 const local='http://127.0.0.1:8001';
 const status=await (await fetch(local+'/api/status')).json();
 const pairing=await (await fetch(local+'/api/pairing')).json();
 const remote=status.mobile.lan_url;
 w=new BrowserWindow({show:false,width:390,height:844,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true}});
 await w.loadURL(remote);
 await waitFor(w,`!document.getElementById('pairing-card').hidden`);
 await w.webContents.executeJavaScript(`document.getElementById('pairing-input').value=${JSON.stringify(pairing.token)}; document.getElementById('pairing-form').requestSubmit();`);
 await waitFor(w,`document.getElementById('pairing-card').hidden && document.getElementById('chat-list').children.length>0`);
 const access=await w.webContents.executeJavaScript(`fetch('/api/status',{headers:{'X-OmniVLA-Pairing':sessionStorage.getItem('omnivla-pairing')}}).then(r=>r.json()).then(r=>r.access)`);
 if(access.is_local || access.remote_control_enabled)throw new Error('Remote read-only policy not applied');
 fs.writeFileSync(out,JSON.stringify({pairedThroughUI:true,remoteReadOnly:true,url:remote},null,2));
 app.exit(0);
}catch(e){fs.writeFileSync(out,JSON.stringify({error:e.stack},null,2));app.exit(1)}finally{if(w&&!w.isDestroyed())w.destroy()}});
