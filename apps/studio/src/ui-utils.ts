import { SidecarRpcError } from "./bridge";

/** Small shared DOM and formatting helpers extracted from the app shell. */

export async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function splitCommaValues(value: string): string[] {
  return [...new Set(value.split(/[,，]/).map((item) => item.trim()).filter(Boolean))];
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character] ?? character);
}

export function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function isRepairableIndexError(error: unknown): boolean {
  if (!(error instanceof SidecarRpcError) || error.data === null || typeof error.data !== "object") {
    return false;
  }
  const data = error.data as { canRebuildIndex?: unknown };
  return data.canRebuildIndex === true;
}
