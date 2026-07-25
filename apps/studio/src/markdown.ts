const FRONTMATTER = /^---\r?\n[\s\S]*?\r?\n---\r?\n/;
const ASSET_REFERENCE = /qbank-asset:([a-zA-Z0-9][a-zA-Z0-9_-]*)/g;

export function bodyForPreview(source: string): string {
  return source.replace(FRONTMATTER, "");
}

export function assetReferences(source: string): string[] {
  const values: string[] = [];
  for (const match of source.matchAll(ASSET_REFERENCE)) {
    const id = match[1];
    if (id !== undefined && !values.includes(id)) values.push(id);
  }
  return values;
}

export function rewriteAssetReferences(
  source: string,
  dataUrls: ReadonlyMap<string, string>,
): string {
  return source.replace(ASSET_REFERENCE, (raw, id: string) => dataUrls.get(id) ?? raw);
}

export function rewriteBackslashMathHtml(html: string, source = html): string {
  const protectedBlocks: string[] = [];
  const protectedHtml = html.replace(/<(pre|code)\b[^>]*>[\s\S]*?<\/\1>/gi, (block) => {
    const index = protectedBlocks.push(block) - 1;
    return `<!--qbank-protected-${index}-->`;
  });
  let rewritten = protectedHtml
    .replace(/\\\[([\s\S]*?)\\\]/g, '<div class="language-math qbank-display-math">$1</div>')
    .replace(/\\\(([\s\S]*?)\\\)/g, '<span class="language-math qbank-inline-math">$1</span>');
  for (const match of source.matchAll(/\\\(([\s\S]*?)\\\)/g)) {
    const tex = match[1];
    if (tex === undefined) continue;
    const visible = `(${escapeHtml(tex)})`;
    rewritten = rewritten.replace(
      visible,
      `<span class="language-math qbank-inline-math">${escapeHtml(tex)}</span>`,
    );
  }
  for (const match of source.matchAll(/\\\[([\s\S]*?)\\\]/g)) {
    const tex = match[1];
    if (tex === undefined) continue;
    rewritten = rewritten.replace(
      /<p\b[^>]*>\s*\[(?:\s*<br\s*\/?>)?[\s\S]*?\](?:\s*<br\s*\/?>)?\s*<\/p>/i,
      `<div class="language-math qbank-display-math">${escapeHtml(tex.trim())}</div>`,
    );
  }
  return rewritten.replace(/<!--qbank-protected-(\d+)-->/g, (_marker, rawIndex: string) => {
    return protectedBlocks[Number(rawIndex)] ?? "";
  });
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function insertAssetReference(source: string, assetId: string): string {
  const reference = `![图形资产](qbank-asset:${assetId})`;
  const heading = /^## 题目\s*$/m;
  const match = heading.exec(source);
  if (match === null) return `${source.trimEnd()}\n\n${reference}\n`;
  const nextSection = source.indexOf("\n## ", match.index + match[0].length);
  const offset = nextSection < 0 ? source.length : nextSection;
  return `${source.slice(0, offset).trimEnd()}\n\n${reference}\n${source.slice(offset)}`;
}

export function nextAssetId(existing: readonly string[]): string {
  const occupied = new Set(existing);
  let index = 1;
  while (occupied.has(`figure-${index}`)) index += 1;
  return `figure-${index}`;
}
