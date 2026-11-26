(() => {
  'use strict';
  const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.pantheon;
  if (!handler) return;
  const listeners = [];
  const scale = () => window.devicePixelRatio || 1;
  window.chrome = window.chrome || {};
  window.chrome.webview = {
    postMessage(text) {
      try {
        const m = JSON.parse(text);
        if (m && m.action === 'mountLayout' && m.data) {
          const d = scale();
          for (const k of ['x', 'y', 'width', 'height']) m.data[k] = Math.round(m.data[k] / d);
          text = JSON.stringify(m);
        }
      } catch (e) {}
      handler.postMessage(String(text));
    },
    addEventListener(type, fn) { if (type === 'message' && typeof fn === 'function') listeners.push(fn); },
    removeEventListener(type, fn) { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); }
  };
  Object.defineProperty(window, '__pantheonDeliver', {
    value: data => { for (const fn of listeners.slice()) { try { fn({data}); } catch (e) { console.error(e); } } },
    writable: false
  });
  const interactive = 'button,a,input,select,textarea,label,[role="button"],.window-controls';
  window.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const target = e.target instanceof Element ? e.target : null;
    if (!target || !target.closest('.app-header') || target.closest(interactive)) return;
    handler.postMessage(JSON.stringify({id: 'window-drag', action: '__drag'}));
  }, true);
  window.addEventListener('dblclick', e => {
    const target = e.target instanceof Element ? e.target : null;
    if (!target || !target.closest('.app-header') || target.closest(interactive)) return;
    handler.postMessage(JSON.stringify({id: 'window-maximize', action: '__maximize'}));
  }, true);
})();
