const { app, BrowserWindow, screen, ipcMain } = require('electron');
const path = require('path');
const http = require('http');

let win;
let server;

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.bounds;

  win = new BrowserWindow({
    width: width,
    height: height,
    x: 0,
    y: 0,
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

  // Enable click-through
  win.setIgnoreMouseEvents(true, { forward: true });

  win.loadFile(path.join(__dirname, 'index.html'));

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

// Setup a small HTTP control server to hide and show the window selectively
function startControlServer() {
  server = http.createServer((req, res) => {
    if (req.url === '/hide') {
      if (win) win.hide();
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('hidden');
    } else if (req.url === '/show') {
      if (win) {
        win.showInactive(); // Show window without stealing active focus
      }
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('shown');
    } else {
      res.writeHead(404);
      res.end();
    }
  });
  
  server.listen(8082, '127.0.0.1', () => {
    console.log('Overlay control server listening on port 8082');
  });
}

app.whenReady().then(() => {
  createWindow();
  startControlServer();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (server) {
    server.close();
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
