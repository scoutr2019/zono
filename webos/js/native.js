// Zono on Android TV: the same app as on LG, but video plays in Android's own player (ExoPlayer: MKV, AC3, 4K, HLS).
// This file only does something inside the Android app (window.ZonoAndroid is the bridge to Kotlin).
// It offers the few things app.js uses of a <video> element, and passes them to the native player.
(function () {
  "use strict";
  var bridge = window.ZonoAndroid;
  if (!bridge) return;
  var listeners = {};
  function fire(type) { (listeners[type] || []).slice().forEach(function (fn) { try { fn({ type: type }); } catch (e) { setTimeout(function () { throw e; }); } }); }
  var state = { src: "", time: 0, duration: NaN, paused: true, error: null };
  var video = {
    textTracks: [], audioTracks: null,
    addEventListener: function (type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener: function (type, fn) { var l = listeners[type]; if (l && l.indexOf(fn) >= 0) l.splice(l.indexOf(fn), 1); },
    getAttribute: function (name) { return name === "src" ? state.src || null : null; },
    removeAttribute: function (name) { if (name === "src") { state.src = ""; state.paused = true; bridge.stop(); } },
    load: function () { if (state.src) { state.error = null; bridge.load(state.src); } },
    play: function () { state.paused = false; bridge.play(); return Promise.resolve(); },
    pause: function () { if (!state.paused) { state.paused = true; bridge.pause(); fire("pause"); } },
    /** Where the picture goes: mode 0 hidden, 1 small picture (x, y, w, h in page pixels), 2 full screen. */
    setRect: function (mode, x, y, w, h) { bridge.rect(mode, x || 0, y || 0, w || 0, h || 0); },
    native: true,
  };
  Object.defineProperty(video, "src", { get: function () { return state.src; }, set: function (url) {
    state.src = url; state.error = null; state.time = 0; state.duration = NaN; bridge.load(url);
  } });
  Object.defineProperty(video, "currentTime", { get: function () { return state.time; }, set: function (t) {
    state.time = Math.max(0, t); bridge.seek(Math.round(state.time * 1000));
  } });
  Object.defineProperty(video, "duration", { get: function () { return state.duration; } });
  Object.defineProperty(video, "paused", { get: function () { return state.paused; } });
  Object.defineProperty(video, "error", { get: function () { return state.error; } });
  /** Called by the native player: what happened, the position and length (seconds), paused, error code. */
  window.ZonoVideoEvent = function (type, position, duration, paused, code) {
    state.time = position || 0;
    state.duration = duration > 0 ? duration : (type === "loadedmetadata" ? Infinity : state.duration);
    if (typeof paused === "boolean") state.paused = paused;
    if (type === "error") state.error = { code: code || 4 };
    fire(type);
  };
  window.ZonoNativeVideo = video;
  document.documentElement.classList.add("android");
})();
