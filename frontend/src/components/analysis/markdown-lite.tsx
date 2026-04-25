/**
 * 极简 markdown 渲染器（不引入额外依赖）。
 *
 * 支持的语法子集（与 prompt 输出完全对齐）：
 *  - ``# / ## / ###`` 标题
 *  - 围栏代码块 ``` ```（含可选语言标识）``
 *  - ``- `` 无序列表
 *  - ``1. `` 有序列表
 *  - ``**粗体**`` / ``*斜体*`` / ``\`内联码\``
 *  - 表格 ``| a | b |``
 *  - 空行 → 段落分隔
 *
 * 不支持：链接 / 图片 / 嵌套引用 / GFM checkbox。
 * 不需要这些是因为 LLM prompt 已禁止输出。
 */

import { Fragment, type ReactNode } from "react";

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  // 用一遍正则分段处理 ``code`` / **bold** / *italic*；优先级 code > bold > italic
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<Fragment key={i++}>{text.slice(last, m.index)}</Fragment>);
    const tok = m[0];
    if (tok.startsWith("`")) {
      out.push(
        <code
          key={i++}
          className="rounded bg-muted/60 px-1 py-0.5 text-[0.85em] font-mono"
        >
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith("**")) {
      out.push(
        <strong key={i++} className="font-semibold text-foreground">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else {
      out.push(
        <em key={i++} className="italic">
          {tok.slice(1, -1)}
        </em>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(<Fragment key={i++}>{text.slice(last)}</Fragment>);
  return out;
}

interface Block {
  kind: "h1" | "h2" | "h3" | "p" | "ul" | "ol" | "code" | "table";
  content: string[];
  lang?: string;
}

function parseBlocks(md: string): Block[] {
  const lines = md.split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    const trimmed = ln.trim();

    // 围栏代码块
    if (trimmed.startsWith("```")) {
      const lang = trimmed.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // 跳过结尾 ```
      blocks.push({ kind: "code", content: buf, lang });
      continue;
    }

    // 标题
    if (/^###\s+/.test(ln)) {
      blocks.push({ kind: "h3", content: [ln.replace(/^###\s+/, "")] });
      i++;
      continue;
    }
    if (/^##\s+/.test(ln)) {
      blocks.push({ kind: "h2", content: [ln.replace(/^##\s+/, "")] });
      i++;
      continue;
    }
    if (/^#\s+/.test(ln)) {
      blocks.push({ kind: "h1", content: [ln.replace(/^#\s+/, "")] });
      i++;
      continue;
    }

    // 表格（连续的 | xxx | yyy | 行）
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        buf.push(lines[i]);
        i++;
      }
      blocks.push({ kind: "table", content: buf });
      continue;
    }

    // 无序列表
    if (/^\s*[-*]\s+/.test(ln)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ul", content: buf });
      continue;
    }

    // 有序列表
    if (/^\s*\d+\.\s+/.test(ln)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ol", content: buf });
      continue;
    }

    // 段落（连续非空行）
    if (trimmed === "") {
      i++;
      continue;
    }
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^#{1,3}\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith("```") &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*\|.*\|\s*$/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "p", content: [buf.join(" ")] });
  }
  return blocks;
}

function Table({ rows }: { rows: string[] }) {
  // 头 + 分隔 + 数据行
  const cells = rows.map((r) =>
    r
      .replace(/^\s*\|/, "")
      .replace(/\|\s*$/, "")
      .split("|")
      .map((c) => c.trim()),
  );
  if (cells.length < 2) {
    return null;
  }
  // 第二行通常是 "---|---" 分隔，若是则跳过
  const headerSeparatorIdx = cells.findIndex((row) =>
    row.every((c) => /^[:\-\s]+$/.test(c)),
  );
  let header = cells[0];
  let body = cells.slice(1);
  if (headerSeparatorIdx === 1) {
    body = cells.slice(2);
  } else if (headerSeparatorIdx === 0) {
    header = [];
    body = cells.slice(1);
  }

  return (
    <div className="my-3 overflow-x-auto rounded-md border border-border/50">
      <table className="w-full text-sm">
        {header.length > 0 && (
          <thead className="bg-muted/40">
            <tr>
              {header.map((h, idx) => (
                <th
                  key={idx}
                  className="px-3 py-2 text-left font-semibold text-foreground"
                >
                  {renderInline(h)}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className="border-t border-border/30">
              {row.map((c, ci) => (
                <td key={ci} className="px-3 py-1.5 text-muted-foreground">
                  {renderInline(c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MarkdownLite({ source }: { source: string }) {
  const blocks = parseBlocks(source);
  return (
    <div className="space-y-3 leading-relaxed text-sm text-foreground/90">
      {blocks.map((b, idx) => {
        switch (b.kind) {
          case "h1":
            return (
              <h1 key={idx} className="text-xl font-bold text-foreground mt-2">
                {renderInline(b.content[0])}
              </h1>
            );
          case "h2":
            return (
              <h2
                key={idx}
                className="text-lg font-semibold text-foreground mt-2 border-b border-border/40 pb-1"
              >
                {renderInline(b.content[0])}
              </h2>
            );
          case "h3":
            return (
              <h3 key={idx} className="text-base font-semibold text-foreground mt-1">
                {renderInline(b.content[0])}
              </h3>
            );
          case "p":
            return (
              <p key={idx} className="text-foreground/85">
                {renderInline(b.content[0])}
              </p>
            );
          case "ul":
            return (
              <ul key={idx} className="list-disc space-y-1 pl-5 marker:text-muted-foreground">
                {b.content.map((c, ci) => (
                  <li key={ci}>{renderInline(c)}</li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={idx} className="list-decimal space-y-1 pl-5 marker:text-muted-foreground">
                {b.content.map((c, ci) => (
                  <li key={ci}>{renderInline(c)}</li>
                ))}
              </ol>
            );
          case "code":
            return (
              <pre
                key={idx}
                className="overflow-x-auto rounded-md border border-border/50 bg-muted/40 p-3 text-xs font-mono leading-relaxed"
              >
                {b.lang && (
                  <div className="mb-1.5 text-[10px] uppercase text-muted-foreground/70">
                    {b.lang}
                  </div>
                )}
                <code>{b.content.join("\n")}</code>
              </pre>
            );
          case "table":
            return <Table key={idx} rows={b.content} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
