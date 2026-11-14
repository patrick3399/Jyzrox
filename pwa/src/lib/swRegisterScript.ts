/**
 * Inline service-worker registration, injected by the root layout with
 * `strategy="afterInteractive"` (i.e. after hydration).
 *
 * Registration still waits for `load` so the worker install never competes
 * with startup, but by the time this script runs `load` has often already
 * fired — a listener added then never runs. Register immediately when the
 * document is already complete.
 */
export const SW_REGISTER_SCRIPT = `
if ('serviceWorker' in navigator) {
  var registerServiceWorker = function() {
    navigator.serviceWorker.register('/sw.js').catch(function(err) {
      console.warn('SW registration failed:', err);
    });
  };
  if (document.readyState === 'complete') {
    registerServiceWorker();
  } else {
    window.addEventListener('load', registerServiceWorker);
  }
}
`
