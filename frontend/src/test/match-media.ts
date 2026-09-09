type MediaQueryListener = (event: MediaQueryListEvent) => void

export function stubMatchMedia(initial: Record<string, boolean>) {
  const listeners = new Map<string, Set<MediaQueryListener>>()

  function matchesFor(query: string): boolean {
    return Boolean(initial[query])
  }

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => {
      const mediaQueryList: MediaQueryList = {
        media: query,
        get matches() {
          return matchesFor(query)
        },
        onchange: null,
        addEventListener: (type: string, listener: EventListenerOrEventListenerObject) => {
          if (type !== 'change' || typeof listener !== 'function') {
            return
          }
          const bucket = listeners.get(query) ?? new Set()
          bucket.add(listener as MediaQueryListener)
          listeners.set(query, bucket)
        },
        removeEventListener: (type: string, listener: EventListenerOrEventListenerObject) => {
          if (type !== 'change' || typeof listener !== 'function') {
            return
          }
          listeners.get(query)?.delete(listener as MediaQueryListener)
        },
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      }
      return mediaQueryList
    },
  })

  return {
    set(query: string, matches: boolean) {
      initial[query] = matches
      const event = { matches, media: query } as MediaQueryListEvent
      listeners.get(query)?.forEach((listener) => {
        listener(event)
      })
    },
  }
}
