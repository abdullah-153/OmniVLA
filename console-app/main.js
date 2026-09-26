const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

let win;
let shutdownRequested = false;

function shutdownBackendAndQuit() {
  if (shutdownRequested) {
    if (process.platform !== 'darwin') app.quit();
    return;
  }
  shutdownRequested = true;
  const http = require('http');
  const finish = () => {
    if (process.platform !== 'darwin') app.quit();
  };
  const req = http.request({
    hostname: '127.0.0.1',
    port: 8000,
    path: '/api/shutdown',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': 2, 'X-OmniVLA-Session': process.env.OMNIVLA_SESSION_TOKEN || '' }
  }, finish);
  req.setTimeout(6000, () => { req.destroy(); finish(); });
  req.on('error', finish);
  req.write('{}');
  req.end();
}

function revealWindow(window) {
  if (!window || window.isDestroyed()) return;
  try {
    if (typeof window.setOpacity === 'function') {
      window.setOpacity(1);
    }
  } catch (_) {}
  window.show();
  window.focus();
}

function createWindow() {
  win = new BrowserWindow({
    title: "OmniVLA",
    width: 1280,
    height: 820,
    minWidth: 1000,
    minHeight: 700,
    frame: false, // Make window frameless for custom title bar
    show: true,
    backgroundColor: "#faf9f5",
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true
    }
  });

  function loadApp() {
    if (win) {
      win.webContents.session.clearCache().catch(() => {});
      win.webContents.session.clearStorageData({ storages: ['serviceworkers', 'cachestorage'] }).catch(() => {});
      win.loadURL('http://127.0.0.1:8000/?t=' + Date.now());
    }
  }

  win.webContents.on('did-fail-load', () => {
    setTimeout(loadApp, 1000);
  });

  win.webContents.on('console-message', (event, level, message, line, sourceId) => {
    const levels = ['DEBUG', 'INFO', 'WARN', 'ERROR'];
    const lvl = levels[level] || 'LOG';
    console.log(`[Electron Console][${lvl}] ${message} (Source: ${sourceId}:${line})`);
  });

  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('http://127.0.0.1:8000/')) {
      event.preventDefault();
    }
  });

  win.once('ready-to-show', () => {
    revealWindow(win);
  });

  win.webContents.on('did-finish-load', () => {
    revealWindow(win);
  });

  loadApp();

  win.on('closed', () => {
    win = null;
  });
}

// Window control IPC channels
ipcMain.handle('window:control', (event, action) => {
  if (!win || !['minimize', 'maximize', 'close'].includes(action)) return;
  if (action === 'minimize') {
    win.minimize();
    return;
  }
  if (action === 'maximize') {
    if (win.isMaximized()) {
      win.unmaximize();
    } else {
      win.maximize();
    }
    return;
  }
  win.close();
});

ipcMain.handle('app:quit', () => {
  shutdownBackendAndQuit();
});

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  shutdownBackendAndQuit();
});
