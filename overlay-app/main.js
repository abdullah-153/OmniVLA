const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');

let win;

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { x, y, width, height } = primaryDisplay.bounds;

  win = new BrowserWindow({
    width: width,
    height: height,
    x,
    y,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true
    }
  });

  // Keep the safety overlay visible to the operator without feeding it back
  // into desktop captures. On Windows Electron maps this to
  // WDA_EXCLUDEFROMCAPTURE, so screenshots no longer need to hide/show the
  // window (which caused visible flicker on every reasoning step).
  win.setContentProtection(true);

  // Enable click-through
  win.setIgnoreMouseEvents(true, { forward: true });

  win.loadURL('http://127.0.0.1:8000/overlay/index.html');
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (url !== 'http://127.0.0.1:8000/overlay/index.html') event.preventDefault();
  });

  win.on('closed', () => {
    win = null;
  });
}

// IPC listener for dynamically controlling ignoreMouseEvents
ipcMain.on('set-ignore-mouse-events', (event, ignore, options) => {
  if (win) {
    win.setIgnoreMouseEvents(ignore, options);
  }
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
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
