export const MAX_PREVIEW_HTML_BYTES = 8 * 1024 * 1024;
export const MAX_FORMULA_CHARACTERS = 16 * 1024;

const REMOVED_ELEMENTS = new Set([
  "script", "iframe", "frame", "frameset", "object", "embed", "applet", "portal",
  "link", "meta", "base", "form", "input", "button", "textarea", "select", "option",
  "video", "audio", "source", "track", "canvas", "foreignobject", "use", "animate",
  "animatemotion", "animatetransform", "set", "style",
]);

const ALLOWED_ELEMENTS = new Set([
  "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre",
  "code", "em", "strong", "del", "s", "ul", "ol", "li", "table", "thead", "tbody",
  "tfoot", "tr", "th", "td", "a", "img", "span", "div", "sup", "sub", "kbd", "mark",
  "details", "summary", "mjx-container", "mjx-assistive-mml", "math", "semantics",
  "annotation", "mrow", "mi", "mn", "mo", "mtext", "ms", "mspace", "msup", "msub",
  "msubsup", "mfrac", "msqrt", "mroot", "mfenced", "mover", "munder", "munderover",
  "mtable", "mtr", "mtd", "svg", "g", "path", "line", "rect", "circle", "ellipse",
  "polygon", "polyline", "text", "tspan", "defs", "clippath",
]);

const SAFE_ATTRIBUTES = new Set([
  "class", "title", "alt", "role", "aria-label", "aria-hidden", "data-math", "data-type",
  "colspan", "rowspan", "start", "reversed", "open", "display", "viewbox", "width", "height",
  "x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "r", "rx", "ry", "d", "points",
  "transform", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
  "stroke-linejoin", "stroke-opacity", "opacity", "preserveaspectratio", "xmlns", "focusable",
]);

function byteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function encodeBase64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function decodeBase64(value: string): string {
  const binary = atob(value);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

function isSafeRasterDataUrl(value: string): boolean {
  return /^data:image\/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=]+$/i.test(value)
    && value.length <= MAX_PREVIEW_HTML_BYTES * 1.5;
}

export function sanitizeSvgDataUrl(value: string): string | null {
  if (!value.toLowerCase().startsWith("data:image/svg+xml")) return null;
  if (value.length > MAX_PREVIEW_HTML_BYTES * 1.5) return null;
  const comma = value.indexOf(",");
  if (comma < 0) return null;
  try {
    const metadata = value.slice(0, comma).toLowerCase();
    const source = metadata.includes(";base64")
      ? decodeBase64(value.slice(comma + 1))
      : decodeURIComponent(value.slice(comma + 1));
    if (byteLength(source) > MAX_PREVIEW_HTML_BYTES) return null;
    const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
    if (parsed.querySelector("parsererror") !== null || parsed.documentElement.localName !== "svg") {
      return null;
    }
    sanitizeTree(parsed.documentElement);
    const serialized = new XMLSerializer().serializeToString(parsed.documentElement);
    return `data:image/svg+xml;base64,${encodeBase64(serialized)}`;
  } catch {
    return null;
  }
}

function sanitizeTree(root: Element): void {
  const elements = root.localName.toLowerCase() === "body"
    ? [...root.querySelectorAll("*")]
    : [root, ...root.querySelectorAll("*")];
  for (const element of elements) {
    const name = element.localName.toLowerCase();
    if (REMOVED_ELEMENTS.has(name)) {
      element.remove();
      continue;
    }
    if (!ALLOWED_ELEMENTS.has(name)) {
      element.replaceWith(...element.childNodes);
      continue;
    }
    for (const attribute of [...element.attributes]) {
      const attributeName = attribute.name.toLowerCase();
      if (
        attributeName.startsWith("on")
        || attributeName === "style"
        || attributeName === "srcset"
        || attributeName === "formaction"
        || (!SAFE_ATTRIBUTES.has(attributeName) && attributeName !== "src" && attributeName !== "href")
      ) {
        element.removeAttribute(attribute.name);
      }
    }
    if (name === "a") {
      const href = element.getAttribute("href") ?? "";
      if (!href.startsWith("#")) element.removeAttribute("href");
      element.setAttribute("rel", "noreferrer noopener");
    }
    if (name === "img") {
      const source = element.getAttribute("src") ?? "";
      const safe = isSafeRasterDataUrl(source) ? source : sanitizeSvgDataUrl(source);
      if (safe === null) {
        const placeholder = element.ownerDocument.createElement("span");
        placeholder.className = "blocked-resource";
        placeholder.textContent = "[已阻止不安全或远程图像]";
        element.replaceWith(placeholder);
      } else {
        element.setAttribute("src", safe);
        element.removeAttribute("loading");
      }
    }
  }
}

export function sanitizePreviewHtml(html: string): string {
  if (byteLength(html) > MAX_PREVIEW_HTML_BYTES) {
    return '<p class="preview-error">预览内容超过 8 MiB 安全上限。</p>';
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  sanitizeTree(parsed.body);
  return parsed.body.innerHTML;
}

function guardDelimitedMath(source: string, pattern: RegExp): string {
  return source.replace(pattern, (whole: string, expression: string) => {
    if (expression.length <= MAX_FORMULA_CHARACTERS) return whole;
    return "\n\n> 公式超过 16 KiB 安全上限，已在预览中省略。\n\n";
  });
}

export function guardMathSource(source: string): string {
  let guarded = guardDelimitedMath(source, /\$\$([\s\S]*?)\$\$/g);
  guarded = guardDelimitedMath(guarded, /\\\[([\s\S]*?)\\\]/g);
  guarded = guardDelimitedMath(guarded, /\\\(([\s\S]*?)\\\)/g);
  guarded = guardDelimitedMath(guarded, /(?<!\$)\$([^\n$]*)\$(?!\$)/g);
  return guarded;
}

function previewStyles(theme: "light" | "dark"): string {
  const dark = theme === "dark";
  return `
    :root { color-scheme: ${dark ? "dark" : "light"}; font: 14px/1.72 "Segoe UI", system-ui, sans-serif; }
    body { margin: 0; padding: 24px 28px 56px; color: ${dark ? "#d9e0e7" : "#25313c"}; background: ${dark ? "#252b31" : "#fbfaf7"}; overflow-wrap: anywhere; }
    h1,h2,h3,h4 { line-height: 1.35; margin: 1.35em 0 .55em; color: ${dark ? "#f0f3f6" : "#17232e"}; }
    h1 { font-size: 1.55rem; } h2 { font-size: 1.25rem; border-bottom: 1px solid ${dark ? "#3a434c" : "#dfe3e4"}; padding-bottom: .3em; }
    p, li { max-width: 78ch; } pre { overflow: auto; padding: 12px; border-radius: 5px; background: ${dark ? "#1d2227" : "#f1f2ef"}; }
    code { font-family: "Cascadia Code", Consolas, monospace; } img { display:block; max-width:100%; height:auto; margin:16px auto; }
    table { border-collapse:collapse; max-width:100%; } th,td { border:1px solid ${dark ? "#45505a" : "#d5dbde"}; padding:6px 9px; }
    a { color:${dark ? "#8db7d4" : "#376b91"}; text-decoration:underline; } .blocked-resource,.preview-error { color:${dark ? "#e1b77b" : "#8a5a22"}; }
    [data-math] { max-width:100%; overflow:auto hidden; } mjx-container { max-width:100%; overflow:auto hidden; }
  `;
}

export function previewDocument(html: string, theme: "light" | "dark"): string {
  const body = sanitizePreviewHtml(html);
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; frame-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'"><style>${previewStyles(theme)}</style></head><body>${body}</body></html>`;
}

export class SecurePreviewFrame {
  readonly element: HTMLIFrameElement;

  constructor(
    host: HTMLElement,
    private readonly onFormulaMenu: (event: MouseEvent, formula: HTMLElement) => void,
  ) {
    const frame = document.createElement("iframe");
    frame.id = "secure-preview";
    frame.className = "secure-preview";
    frame.title = "隔离的题目预览";
    frame.setAttribute("sandbox", "allow-same-origin");
    frame.referrerPolicy = "no-referrer";
    frame.addEventListener("load", () => {
      const previewDocument = frame.contentDocument;
      if (previewDocument === null) return;
      previewDocument.addEventListener("click", (event) => {
        const target = event.target as Element | null;
        if (typeof target?.closest === "function" && target.closest("a") !== null) {
          event.preventDefault();
        }
      });
      previewDocument.addEventListener("contextmenu", (event) => {
        const target = event.target as Element | null;
        if (typeof target?.closest !== "function") return;
        const formula = target.closest<HTMLElement>("[data-math]");
        if (formula === null) return;
        event.preventDefault();
        this.onFormulaMenu(event, formula);
      });
    });
    host.append(frame);
    this.element = frame;
  }

  render(html: string, theme: "light" | "dark"): void {
    this.element.srcdoc = previewDocument(html, theme);
  }

  clear(theme: "light" | "dark"): void {
    this.render('<p class="muted">选择一道题目以显示预览。</p>', theme);
  }
}
