import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// ── jsdom shims used by components/charts/tests ───────────────────────────────

// Recharts / ResponsiveContainer relies on ResizeObserver, absent in jsdom. The stub calls
// the callback once on observe() with a concrete size so ResponsiveContainer measures a real
// box (otherwise it stays 0×0 and Recharts renders nothing).
class ResizeObserverStub {
  private cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe(el: Element) {
    this.cb(
      [{ target: el, contentRect: { width: 400, height: 240 } } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// matchMedia is referenced by some UI code; jsdom does not implement it.
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// Minimal EventSource stub (captures listeners) so realProvider SSE code can be constructed
// in tests. The api-client tests drive the MOCK provider (setTimeout-based), so this stub
// only needs to exist, not to fire real network events.
if (typeof globalThis.EventSource === "undefined") {
  class EventSourceStub {
    url: string;
    listeners: Record<string, Array<(e: MessageEvent) => void>> = {};
    onerror: ((e: Event) => void) | null = null;
    constructor(url: string) {
      this.url = url;
    }
    addEventListener(type: string, cb: (e: MessageEvent) => void) {
      (this.listeners[type] ??= []).push(cb);
    }
    removeEventListener(type: string, cb: (e: MessageEvent) => void) {
      this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== cb);
    }
    close() {}
  }
  // @ts-expect-error - assigning to the jsdom global
  globalThis.EventSource = EventSourceStub;
}
