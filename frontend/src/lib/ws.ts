// WebSocket 封装：自动重连 + 心跳 + 订阅参数记忆。

type AnyMsg = Record<string, unknown>;

export interface WsClientOptions<T = AnyMsg> {
  path: "/ws/dashboard" | "/ws/logs";
  onMessage: (msg: T) => void;
  onStatus?: (status: WsStatus) => void;
  /** 连接建立后要发的订阅帧（用对象形式；会在每次重连后自动重放）。 */
  subscribeFrame?: AnyMsg | null;
  heartbeatMs?: number;
}

export type WsStatus = "connecting" | "open" | "closed" | "error";

export class WsClient<T = AnyMsg> {
  private ws: WebSocket | null = null;
  private alive = true;
  private retry = 0;
  private heartbeatTimer: number | null = null;
  private subscribeFrame: AnyMsg | null;
  private status: WsStatus = "closed";

  constructor(private readonly opts: WsClientOptions<T>) {
    this.subscribeFrame = opts.subscribeFrame ?? null;
  }

  setSubscribeFrame(frame: AnyMsg | null): void {
    this.subscribeFrame = frame;
    if (this.ws && this.ws.readyState === WebSocket.OPEN && frame) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  connect(): void {
    if (!this.alive) return;
    this._setStatus("connecting");

    const base = (import.meta as ImportMeta & { env: { VITE_WS_BASE?: string } })
      .env.VITE_WS_BASE;
    let url: string;
    if (base) {
      url = base + this.opts.path;
    } else {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      url = `${proto}://${window.location.host}${this.opts.path}`;
    }

    try {
      this.ws = new WebSocket(url);
    } catch (e) {
      console.error("[ws] ctor 失败", e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.retry = 0;
      this._setStatus("open");
      if (this.subscribeFrame) {
        this.ws?.send(JSON.stringify(this.subscribeFrame));
      }
      this._startHeartbeat();
    };

    this.ws.onmessage = (ev) => {
      try {
        const parsed = JSON.parse(ev.data as string) as T;
        this.opts.onMessage(parsed);
      } catch (e) {
        console.warn("[ws] 解析失败", e);
      }
    };

    this.ws.onerror = () => this._setStatus("error");

    this.ws.onclose = () => {
      this._stopHeartbeat();
      this._setStatus("closed");
      this._scheduleReconnect();
    };
  }

  close(): void {
    this.alive = false;
    this._stopHeartbeat();
    try {
      this.ws?.close();
    } catch {
      /* noop */
    }
    this.ws = null;
  }

  send(frame: AnyMsg): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  private _setStatus(s: WsStatus) {
    if (this.status !== s) {
      this.status = s;
      this.opts.onStatus?.(s);
    }
  }

  private _startHeartbeat() {
    const ms = this.opts.heartbeatMs ?? 20_000;
    this._stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: "ping" }));
      }
    }, ms);
  }

  private _stopHeartbeat() {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private _scheduleReconnect() {
    if (!this.alive) return;
    this.retry += 1;
    const delay = Math.min(1000 * 2 ** Math.min(this.retry, 5), 15_000);
    window.setTimeout(() => this.connect(), delay);
  }
}
