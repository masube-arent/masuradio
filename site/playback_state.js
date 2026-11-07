/* MASURADIO playback state. Browser and Node-compatible, no dependencies. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MasuPlayback = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  const PREFIX = 'masuradio:position:v1:';
  const MIN_SECONDS = 4;
  function validPoint(value, duration) {
    return Number.isFinite(value) && value >= MIN_SECONDS &&
      (!Number.isFinite(duration) || duration <= 0 || value < duration - 5);
  }
  function createStore(storage) {
    const key = id => PREFIX + encodeURIComponent(String(id));
    return {
      get(id, duration) {
        if (!id) return null;
        try {
          const n = Number(storage.getItem(key(id)));
          return validPoint(n, duration) ? n : null;
        } catch (_) { return null; }
      },
      set(id, seconds, duration) {
        if (!id || !validPoint(seconds, duration)) return false;
        try { storage.setItem(key(id), String(Math.floor(seconds))); return true; }
        catch (_) { return false; }
      },
      clear(id) {
        if (!id) return;
        try { storage.removeItem(key(id)); } catch (_) { /* private mode */ }
      }
    };
  }
  function safeChapters(episode) {
    const duration = Number(episode && episode.duration_seconds) || Infinity;
    if (!episode || !Array.isArray(episode.chapters)) return [];
    const result = [], seen = new Set();
    for (const chapter of episode.chapters) {
      const start = Number(chapter && chapter.start_seconds);
      if (!Number.isFinite(start) || start < 0 || start >= duration ||
          !chapter || typeof chapter.title !== 'string' || !chapter.title.trim() || seen.has(start)) continue;
      seen.add(start);
      result.push({title: chapter.title, start_seconds: start});
    }
    return result.sort((a, b) => a.start_seconds - b.start_seconds);
  }
  function createController(audio, storage, callbacks = {}, now = () => Date.now()) {
    const store = createStore(storage);
    let current = null, lastWrite = 0, pending = null;
    const notify = () => callbacks.onResumeAvailability &&
      callbacks.onResumeAvailability(store.get(current && current.date, current && current.duration_seconds));
    const currentId = () => current && current.date;
    const duration = () => current && current.duration_seconds;
    function persist(force = false) {
      if (!currentId() || audio.ended) return;
      const position = Number(audio.currentTime);
      if (force || now() - lastWrite >= 5000) {
        store.set(currentId(), position, duration());
        lastWrite = now();
      }
    }
    function seek(seconds) {
      if (!current || !Number.isFinite(seconds) || seconds < 0) return false;
      const target = Math.min(seconds, Math.max(0, Number(duration()) - 1));
      if (audio.readyState >= 1) audio.currentTime = target;
      else pending = target;
      return true;
    }
    function playFrom(seconds, clear = false) {
      if (!current) return false;
      if (clear) store.clear(currentId());
      seek(seconds);
      if (typeof audio.play === 'function') {
        const promise = audio.play(); // direct user click only
        if (promise && typeof promise.catch === 'function') promise.catch(() => {});
      }
      notify();
      return true;
    }
    function select(episode) {
      if (currentId()) persist(true);
      if (typeof audio.pause === 'function') audio.pause();
      pending = null;
      current = episode || null;
      lastWrite = 0;
      if (episode) {
        audio.src = './' + episode.audio;
        if (typeof audio.load === 'function') audio.load();
      }
      notify();
      if (callbacks.onChapters) callbacks.onChapters(safeChapters(episode));
      // Never invoke play() on selection or load.
    }
    function resume() {
      const seconds = store.get(currentId(), duration());
      if (seconds === null) return false;
      return playFrom(seconds);
    }
    function startOver() { return playFrom(0, true); }
    function chapter(index) {
      const item = safeChapters(current)[index];
      if (!item) return false;
      return seek(item.start_seconds);
    }
    function onMetadata() {
      if (pending !== null) {
        audio.currentTime = pending;
        pending = null;
      }
    }
    function onEnded() { store.clear(currentId()); lastWrite = 0; notify(); }
    return {
      select, resume, startOver, chapter, persist, onMetadata, onEnded,
      getCurrent: () => current,
      getResumePoint: () => store.get(currentId(), duration()),
      getChapters: () => safeChapters(current)
    };
  }
  return {createStore, createController, safeChapters};
});