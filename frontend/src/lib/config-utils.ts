import type {
  ConfigItemMeta,
  ConfigItemType,
  ConfigValue,
} from "./types";

/** 从嵌套对象中按 "a.b.c" 读取值 */
export function getByPath(
  obj: unknown,
  path: string,
): unknown {
  if (obj === null || obj === undefined) return undefined;
  const parts = path.split(".");
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[p];
    if (cur === undefined) return undefined;
  }
  return cur;
}

/** 是否数字型（包括百分比/权重/整数） */
export function isNumericType(t: ConfigItemType): boolean {
  return t === "number" || t === "int" || t === "percent" || t === "weight";
}

/** 把 unknown 适配成本字段 meta 期望的 ConfigValue 类型，用于首次载入表单初值 */
export function coerceToFieldValue(
  raw: unknown,
  meta: ConfigItemMeta,
): ConfigValue {
  const t = meta.type;
  if (raw === undefined || raw === null) {
    return t === "bool"
      ? false
      : isNumericType(t)
        ? 0
        : t === "array"
          ? []
          : t === "enum"
            ? (meta.options?.[0] ?? "")
            : "";
  }
  switch (t) {
    case "bool":
      return Boolean(raw);
    case "number":
    case "int":
    case "percent":
    case "weight":
      return typeof raw === "number" ? raw : Number(raw);
    case "enum":
    case "string":
      return String(raw);
    case "array":
      if (Array.isArray(raw)) return raw as number[] | string[];
      return [];
  }
}

/** 两个配置值是否相等（用于 dirty 判定） */
export function valuesEqual(a: ConfigValue, b: ConfigValue): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
    return true;
  }
  return a === b;
}

/** 展示值为字符串（审计/diff 用） */
export function formatConfigValue(v: ConfigValue | unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return `[${v.join(", ")}]`;
  if (typeof v === "number") return String(v);
  return String(v);
}

/** percent/weight 统一按照 meta 决定显示方式：percent 乘 100 加 % */
export function formatForDisplay(
  v: ConfigValue,
  meta: ConfigItemMeta,
): string {
  if (meta.type === "percent" && typeof v === "number") {
    return `${(v * 100).toFixed(2)}%`;
  }
  if (meta.type === "weight" && typeof v === "number") {
    return v.toFixed(2);
  }
  return formatConfigValue(v);
}
