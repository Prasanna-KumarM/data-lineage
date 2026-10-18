// Existing walkthrough tests start on the walkthrough page; replaceState avoids a stray hashchange.
beforeEach(() => {
  window.history.replaceState(null, '', '#/lineage')
})

// React Flow measures its container; jsdom has no layout, so give it the minimum it needs.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
globalThis.DOMMatrixReadOnly ??= class {
  m22 = 1
  constructor(transform?: string) {
    const scale = /scale\(([^)]+)\)/.exec(transform ?? '')
    if (scale) this.m22 = Number(scale[1])
  }
} as unknown as typeof DOMMatrixReadOnly
