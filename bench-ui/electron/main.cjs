// Bench UI shell: spawns bus_engine.py and bridges its line protocol to the renderer.
// No camera, no updater — this is the Phase 1 heartbeat host from BOUNDARY.md.
const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let win = null;
let engine = null;
let stdoutBuffer = '';

const ENGINE_PATH = path.join(__dirname, '..', '..', 'bus_engine.py');

function startEngine() {
  engine = spawn('python', ['-u', ENGINE_PATH], {
    cwd: path.dirname(ENGINE_PATH),
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  engine.stdout.on('data', (chunk) => {
    stdoutBuffer += chunk.toString();
    let idx;
    while ((idx = stdoutBuffer.indexOf('\n')) >= 0) {
      const line = stdoutBuffer.slice(0, idx).replace(/\r$/, '');
      stdoutBuffer = stdoutBuffer.slice(idx + 1);
      if (line && win && !win.isDestroyed()) {
        win.webContents.send('engine-out', line);
      }
    }
  });

  engine.stderr.on('data', (chunk) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('engine-err', chunk.toString());
    }
  });

  engine.on('exit', (code) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('engine-out', `[SHELL] bus_engine exited with code ${code}`);
    }
    engine = null;
  });
}

ipcMain.on('send-to-engine', (_event, line) => {
  if (engine && engine.stdin.writable) {
    engine.stdin.write(String(line) + '\n');
  }
});

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    backgroundColor: '#101410',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL || !app.isPackaged) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL || 'http://localhost:5173');
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

app.whenReady().then(() => {
  startEngine();
  createWindow();
});

app.on('window-all-closed', () => {
  if (engine) {
    try { engine.stdin.write('STOP_CAN\n'); } catch (_) { /* engine already gone */ }
    engine.kill();
  }
  app.quit();
});
