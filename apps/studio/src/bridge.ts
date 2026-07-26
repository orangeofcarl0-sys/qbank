import { Command, type Child } from "@tauri-apps/plugin-shell";
import type { InitializeResult, JsonValue, RpcBridge } from "./protocol";

interface RpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

interface PendingRequest {
  resolve(value: unknown): void;
  reject(reason: Error): void;
  timeout: number;
}

export class SidecarRpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = "SidecarRpcError";
  }
}

export class TauriRpcBridge implements RpcBridge {
  private child: Child | null = null;
  private nextId = 1;
  private stdoutBuffer = "";
  private pending = new Map<number, PendingRequest>();
  private exitListeners = new Set<(reason: string) => void>();
  private startPromise: Promise<InitializeResult> | null = null;

  start(): Promise<InitializeResult> {
    if (this.startPromise !== null) return this.startPromise;
    this.startPromise = this.spawnAndInitialize();
    return this.startPromise;
  }

  async request<T>(method: string, params: Record<string, JsonValue> = {}): Promise<T> {
    if (this.child === null && method !== "initialize") await this.start();
    if (this.child === null) throw new Error("qbank sidecar is not running");
    const id = this.nextId++;
    const payload = `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`;
    const response = new Promise<T>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`sidecar request timed out: ${method}`));
      }, method === "asset.render" ? 120_000 : 20_000);
      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timeout,
      });
    });
    try {
      await this.child.write(payload);
    } catch (error) {
      const pending = this.pending.get(id);
      if (pending !== undefined) {
        window.clearTimeout(pending.timeout);
        this.pending.delete(id);
      }
      throw error;
    }
    return response;
  }

  async stop(): Promise<void> {
    const child = this.child;
    if (child === null) return;
    try {
      await this.request("application.shutdown");
    } catch {
      await child.kill();
    } finally {
      this.child = null;
      this.startPromise = null;
      this.rejectPending("sidecar stopped");
    }
  }

  onExit(listener: (reason: string) => void): () => void {
    this.exitListeners.add(listener);
    return () => this.exitListeners.delete(listener);
  }

  private async spawnAndInitialize(): Promise<InitializeResult> {
    const command = Command.sidecar("binaries/qbank-sidecar", [], {
      encoding: "utf-8",
      env: { PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
    });
    command.stdout.on("data", (chunk) => this.consumeStdout(chunk));
    command.stderr.on("data", (chunk) => console.warn(`[qbank-sidecar] ${chunk}`));
    command.on("error", (error) => this.handleExit(`sidecar error: ${error}`));
    command.on("close", ({ code, signal }) => {
      this.handleExit(`sidecar exited (code ${String(code)}, signal ${String(signal)})`);
    });
    this.child = await command.spawn();
    return this.request<InitializeResult>("initialize", { studioVersion: "0.3.0-beta.2" });
  }

  private consumeStdout(chunk: string): void {
    this.stdoutBuffer += chunk;
    for (;;) {
      const newline = this.stdoutBuffer.indexOf("\n");
      if (newline < 0) break;
      const line = this.stdoutBuffer.slice(0, newline).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
      if (line.length > 0) this.resolveLine(line);
    }
  }

  private resolveLine(line: string): void {
    let message: RpcResponse;
    try {
      message = JSON.parse(line) as RpcResponse;
    } catch {
      this.handleExit("sidecar produced invalid protocol output");
      return;
    }
    const pending = this.pending.get(message.id);
    if (pending === undefined) return;
    window.clearTimeout(pending.timeout);
    this.pending.delete(message.id);
    if (message.error !== undefined) {
      pending.reject(
        new SidecarRpcError(message.error.code, message.error.message, message.error.data),
      );
    } else {
      pending.resolve(message.result);
    }
  }

  private handleExit(reason: string): void {
    if (this.child === null) return;
    this.child = null;
    this.startPromise = null;
    this.rejectPending(reason);
    for (const listener of this.exitListeners) listener(reason);
  }

  private rejectPending(reason: string): void {
    for (const pending of this.pending.values()) {
      window.clearTimeout(pending.timeout);
      pending.reject(new Error(reason));
    }
    this.pending.clear();
  }
}
