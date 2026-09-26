const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', {
  windowControl: (action) => ipcRenderer.invoke('window:control', action),
  openExternal: (url) => ipcRenderer.invoke('external:open', url),
  quitApp: () => ipcRenderer.invoke('app:quit')
});
