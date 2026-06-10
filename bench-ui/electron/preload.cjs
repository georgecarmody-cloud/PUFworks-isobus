const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('benchAPI', {
  sendToEngine: (line) => ipcRenderer.send('send-to-engine', line),
  onEngineOut: (callback) => ipcRenderer.on('engine-out', (_event, line) => callback(line)),
  onEngineErr: (callback) => ipcRenderer.on('engine-err', (_event, text) => callback(text)),
});
