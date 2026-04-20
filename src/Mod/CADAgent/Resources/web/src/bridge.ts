// Typed QWebChannel bridge client.
//
// Qt exposes a global `qt.webChannelTransport` and a `QWebChannel` constructor
// loaded via the inline <script src="qrc:///qtwebchannel/qwebchannel.js">.
// We wrap both in a Promise so the React app can `await getBridge()` once.

export interface Bridge {
  // Slots (JS -> Python)
  submit(text: string): void;
  stop(): void;
  decidePermission(reqId: string, allowed: boolean, reason: string): void;

  // Signals (Python -> JS). Qt adds `.connect(fn)` / `.disconnect(fn)` to each.
  assistantText:     QtSignal<[string]>;
  thinkingText:      QtSignal<[string]>;
  toolUse:           QtSignal<[string, string, string]>;
  toolResult:        QtSignal<[string, string, boolean]>;
  permissionRequest: QtSignal<[string, string, string]>;
  turnComplete:      QtSignal<[number]>;
  errorText:         QtSignal<[string]>;
  systemText:        QtSignal<[string]>;
  bypassChanged:     QtSignal<[boolean]>;
}

interface QtSignal<A extends unknown[]> {
  connect(fn: (...args: A) => void): void;
  disconnect(fn: (...args: A) => void): void;
}

declare global {
  interface Window {
    qt: { webChannelTransport: unknown };
    QWebChannel: new (
      transport: unknown,
      init: (channel: { objects: { bridge: Bridge } }) => void,
    ) => unknown;
  }
}

let cached: Promise<Bridge> | null = null;

export function getBridge(): Promise<Bridge> {
  if (cached) return cached;
  cached = new Promise((resolve) => {
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
      resolve(channel.objects.bridge);
    });
  });
  return cached;
}
