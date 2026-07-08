import '@testing-library/jest-dom/vitest';

// jsdom has no layout engine. @tanstack/react-virtual measures its scroll
// element via ResizeObserver + getBoundingClientRect — feed it a fixed viewport.
const rect = {
  width: 1024,
  height: 800,
  top: 0,
  left: 0,
  bottom: 800,
  right: 1024,
  x: 0,
  y: 0,
  toJSON: () => ({}),
} satisfies DOMRect;

class ResizeObserverStub {
  constructor(private readonly callback: ResizeObserverCallback) {}
  observe(target: Element): void {
    this.callback(
      [
        {
          target,
          contentRect: rect,
          borderBoxSize: [{ inlineSize: rect.width, blockSize: rect.height }],
          contentBoxSize: [{ inlineSize: rect.width, blockSize: rect.height }],
          devicePixelContentBoxSize: [{ inlineSize: rect.width, blockSize: rect.height }],
        } as unknown as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    );
  }
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
Element.prototype.getBoundingClientRect = () => rect;
Element.prototype.scrollIntoView = () => {};

// jsdom's Blob/File lack .text() (standard in every real browser) — back-fill
// via FileReader so CSV-upload flows are testable.
if (typeof Blob.prototype.text !== 'function') {
  Blob.prototype.text = function text(this: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve(reader.result as string);
      };
      reader.onerror = () => {
        reject(new Error('FileReader failed'));
      };
      reader.readAsText(this);
    });
  };
}
