"use client";

import { useState } from "react";

type Schema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minLength?: number;
  maxLength?: number;
  items?: Schema;
  properties?: Record<string, Schema>;
  additionalProperties?: boolean | Schema;
  anyOf?: Schema[];
  allOf?: Schema[];
  $ref?: string;
  $defs?: Record<string, Schema>;
};

const input = "h-[30px] w-full rounded-md border border-line-strong bg-canvas px-2 text-xs";

/** Resolve `$ref`s against the root's `$defs`, and unwrap `X | None` into (X, nullable). */
export function resolve(root: Schema, s: Schema): { schema: Schema; nullable: boolean } {
  let cur = s;
  let nullable = false;
  for (let i = 0; i < 5; i++) {
    if (cur.$ref) {
      const name = cur.$ref.split("/").pop()!;
      cur = { ...(root.$defs?.[name] ?? {}), description: cur.description ?? root.$defs?.[name]?.description };
    } else if (cur.anyOf) {
      const others = cur.anyOf.filter((o) => o.type !== "null");
      nullable = nullable || others.length < cur.anyOf.length;
      cur = { ...others[0], description: cur.description ?? others[0]?.description, default: cur.default ?? others[0]?.default };
    } else if (cur.allOf?.length === 1) {
      cur = { ...cur.allOf[0], description: cur.description };
    } else break;
  }
  return { schema: cur, nullable };
}

export function humanize(key: string): string {
  const s = key.replace(/_/g, " ").replace(/\bfps\b/, "FPS").replace(/\bid\b/, "ID");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function JsonField({ id, value, onChange }: { id: string; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <textarea
        id={id}
        value={text}
        rows={Math.min(8, Math.max(2, text.split("\n").length))}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value || "{}");
            if (typeof parsed !== "object" || Array.isArray(parsed) || parsed === null) throw new Error("an object: {…}");
            setError(null);
            onChange(parsed);
          } catch (err) {
            setError(`Must be JSON: ${err instanceof Error ? err.message : String(err)}`);
          }
        }}
        className="w-full rounded-md border border-line-strong bg-canvas px-2 py-1 font-mono text-[11px]"
      />
      {error ? <span className="text-[11px] text-error">{error}</span> : null}
    </>
  );
}

function Field({ root, name, schema: raw, value, onChange, path }: {
  root: Schema;
  name: string;
  schema: Schema;
  value: unknown;
  onChange: (v: unknown) => void;
  path: string;
}) {
  const { schema, nullable } = resolve(root, raw);
  const id = `cfg-${path}`;
  const label = <label htmlFor={id} className="font-medium text-ink">{humanize(name)}</label>;
  const help = schema.description ? <span className="text-[11px] text-ink-3">{schema.description}</span> : null;

  if (schema.type === "boolean") {
    return (
      <div className="flex flex-col gap-0.5">
        <label className="flex items-center gap-2 font-medium">
          <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {humanize(name)}
        </label>
        {help}
      </div>
    );
  }
  if (schema.type === "integer" || schema.type === "number") {
    const min = schema.minimum ?? schema.exclusiveMinimum;
    const max = schema.maximum ?? schema.exclusiveMaximum;
    return (
      <div className="flex flex-col gap-1">
        {label}
        <input
          id={id}
          type="number"
          className={input}
          min={min}
          max={max}
          step={schema.type === "integer" ? 1 : "any"}
          value={value == null ? "" : String(value)}
          placeholder={nullable ? "Not set" : undefined}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v === "" ? (nullable ? null : schema.default ?? 0) : schema.type === "integer" ? Math.round(Number(v)) : Number(v));
          }}
        />
        {help}
      </div>
    );
  }
  if (schema.type === "array") {
    const items = resolve(root, schema.items ?? {}).schema;
    const list = Array.isArray(value) ? (value as unknown[]) : [];
    if (items.enum) {
      return (
        <fieldset className="flex min-w-0 flex-col gap-1">
          <legend className="font-medium">{humanize(name)}</legend>
          <div className="flex flex-wrap gap-1.5">
            {items.enum.map((opt) => {
              const on = list.includes(opt);
              return (
                <label key={String(opt)} className="flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5">
                  <input type="checkbox" checked={on} onChange={() => onChange(on ? list.filter((x) => x !== opt) : [...list, opt])} />
                  {String(opt).replace(/_/g, " ")}
                </label>
              );
            })}
          </div>
          {help}
        </fieldset>
      );
    }
    return (
      <div className="flex flex-col gap-1">
        {label}
        <input
          id={id}
          className={input}
          value={list.join(", ")}
          placeholder="Comma-separated; empty for all"
          onChange={(e) => onChange(e.target.value.split(",").map((x) => x.trim()).filter(Boolean))}
        />
        {help}
      </div>
    );
  }
  if (schema.type === "object" && schema.properties) {
    const obj = (value ?? {}) as Record<string, unknown>;
    return (
      <fieldset className="flex min-w-0 flex-col gap-2 rounded-md border border-line p-2">
        <legend className="px-1 font-medium">{humanize(name)}</legend>
        {Object.entries(schema.properties).map(([k, sub]) => (
          <Field key={k} root={root} name={k} schema={sub} value={obj[k]} path={`${path}.${k}`} onChange={(v) => onChange({ ...obj, [k]: v })} />
        ))}
      </fieldset>
    );
  }
  if (schema.type === "object") {
    return (
      <div className="flex flex-col gap-1">
        {label}
        <JsonField id={id} value={value} onChange={onChange} />
        {help}
      </div>
    );
  }
  if (schema.enum) {
    return (
      <div className="flex flex-col gap-1">
        {label}
        <select id={id} className={input} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {schema.enum.map((o) => <option key={String(o)} value={String(o)}>{String(o).replace(/_/g, " ")}</option>)}
        </select>
        {help}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {label}
      <input
        id={id}
        className={input}
        value={value == null ? "" : String(value)}
        maxLength={schema.maxLength}
        placeholder={nullable ? "Not set: the configured default" : undefined}
        onChange={(e) => onChange(e.target.value === "" && nullable ? null : e.target.value)}
      />
      {help}
    </div>
  );
}

/** Edit a step's config from its JSON schema (the API's Pydantic model). */
export function ConfigForm({ schema, value, onChange }: {
  schema: Record<string, unknown>;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const root = schema as Schema;
  const props = root.properties ?? {};
  if (!Object.keys(props).length) return <p className="text-xs text-ink-3">This step has no settings.</p>;
  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {Object.entries(props).map(([k, s]) => (
        <Field key={k} root={root} name={k} schema={s} value={value[k]} path={k} onChange={(v) => onChange({ ...value, [k]: v })} />
      ))}
    </div>
  );
}
