// Glance dashboard — Electron wrapper.
// - Fullscreen kiosk window of the dashboard (served by the feed service).
// - Auto-popup on idle (screensaver-like): when you step away it appears fullscreen;
//   when you come back it hides so you can use your Mac.
// - Tray menu + global shortcut (Ctrl+Cmd+D) to summon/dismiss manually.
const { app, BrowserWindow, powerMonitor, Tray, Menu, globalShortcut, nativeImage } = require('electron');

const DASH_URL  = process.env.GLANCE_URL  || 'http://localhost:8090/';
const IDLE_SECS = Number(process.env.GLANCE_IDLE || 300);   // 5 min idle → popup
let win, tray, autoShown = false, idleEnabled = true;

// one running instance only; a second launch just summons the existing one
if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => showDash(false));
// make Cmd+Q (and any real quit) actually quit, not get swallowed by the hide-on-close handler
app.on('before-quit', () => { app.isQuitting = true; });

function createWindow() {
  win = new BrowserWindow({
    width: 1920, height: 1080, show: false,
    backgroundColor: '#05061a', title: 'Glance', icon: undefined,
    webPreferences: { backgroundThrottling: false },
  });
  win.loadURL(DASH_URL);
  // closing the window just hides it — app keeps living in the tray
  win.on('close', (e) => { if (!app.isQuitting) { e.preventDefault(); hideDash(); } });
  // Escape (and Cmd+W) dismiss the dashboard cleanly
  win.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    if (input.key === 'Escape' || (input.meta && input.key.toLowerCase() === 'w')) { e.preventDefault(); hideDash(); }
  });
}

function showDash(auto) {
  if (!win || win.isDestroyed()) createWindow();
  autoShown = !!auto;
  win.setAlwaysOnTop(!!auto, 'screen-saver');   // float over everything when auto-triggered
  if (!win.isSimpleFullScreen()) win.setSimpleFullScreen(true);  // NOT native fullscreen (avoids the black-Space bug)
  win.show(); win.focus();
}
function hideDash() {
  if (win && !win.isDestroyed()) {
    win.setAlwaysOnTop(false);
    win.setSimpleFullScreen(false);
    win.hide();
  }
  autoShown = false;
}

app.whenReady().then(() => {
  createWindow();
  showDash(false);   // show once on launch

  tray = new Tray(nativeImage.createEmpty());
  tray.setTitle('◧ Glance');
  const menu = Menu.buildFromTemplate([
    { label: 'Show dashboard', click: () => showDash(false) },
    { label: 'Hide', click: hideDash },
    { type: 'separator' },
    { label: 'Auto-popup when idle', type: 'checkbox', checked: true, click: (mi) => { idleEnabled = mi.checked; } },
    { type: 'separator' },
    { label: 'Quit Glance', click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray.setToolTip('Glance dashboard');
  tray.setContextMenu(menu);

  globalShortcut.register('Control+Command+D', () =>
    (win && win.isVisible() && !autoShown) ? hideDash() : showDash(false));

  // idle watcher
  setInterval(() => {
    if (!idleEnabled) return;
    const idle = powerMonitor.getSystemIdleTime();
    if (idle >= IDLE_SECS && (!win || !win.isVisible())) showDash(true);
    else if (autoShown && idle < 3) hideDash();   // user returned → step aside
  }, 2000);
});

app.on('window-all-closed', () => {});  // stay alive in tray
