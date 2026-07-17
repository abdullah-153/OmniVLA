const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', {
  windowControl: (action) => ipcRenderer.invoke('window:control', action)
});
