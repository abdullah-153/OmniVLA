const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('overlayAPI', {
  setIgnoreMouseEvents: (ignore, forward = false) =>
    ipcRenderer.send('set-ignore-mouse-events', ignore, { forward })
});
