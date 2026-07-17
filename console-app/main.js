const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

let win;

function revealWindow(window) {
  if (!window || window.isDestroyed()) return;
  if (typeof window.setOpacity !== 'function') {
    window.show();
    return;
  }

  window.setOpacity(0);
  window.show();
  const frames = 9;
  let frame = 0;
  const fadeTimer = setInterval(() => {
    if (!window || window.isDestroyed()) {
      clearInterval(fadeTimer);
      return;
    }
    frame += 1;
    window.setOpacity(Math.min(1, frame / frames));
    if (frame >= frames) clearInterval(fadeTimer);
  }, 20);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1000,
    minHeight: 700,
    frame: false, // Make window frameless for custom title bar
    show: false,
    backgroundColor: "#08090a",
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

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  const http = require('http');
  const req = http.get('http://127.0.0.1:8000/shutdown', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
  req.on('error', () => {
    if (process.platform !== 'darwin') {
      app.quit();
    }
  });
});
