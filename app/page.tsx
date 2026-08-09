"use client";

import { useEffect, useMemo, useState } from "react";
import type { Label, LabelSize } from "@/lib/types";

const SWATCHES = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899"];
const SIZES: LabelSize[] = ["small", "medium", "large"];

export default function Home() {
  const [labels, setLabels] = useState<Label[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [text, setText] = useState("");
  const [color, setColor] = useState(SWATCHES[4]);
  const [size, setSize] = useState<LabelSize>("medium");
  const [quantity, setQuantity] = useState(1);

  async function refresh() {
    const res = await fetch("/api/labels");
    const data = await res.json();
    setLabels(data.labels ?? []);
    setLoading(false);
  }

  useEffect(() => {
    refresh().catch(() => {
      setError("Failed to load labels");
      setLoading(false);
    });
  }, []);

  const totalPrints = useMemo(
    () => labels.reduce((sum, label) => sum + label.quantity, 0),
    [labels],
  );

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const res = await fetch("/api/labels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, text, color, size, quantity }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Could not create label");
      }
      setName("");
      setText("");
      setQuantity(1);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    const res = await fetch(`/api/labels/${id}`, { method: "DELETE" });
    if (res.ok) {
      await refresh();
    } else {
      setError("Could not delete label");
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand__mark">LO</div>
          <div>
            <div className="brand__name">LABELOS</div>
            <div className="brand__tag">Label design &amp; management studio</div>
          </div>
        </div>
        <div className="pill">
          <strong>{labels.length}</strong> labels · <strong>{totalPrints}</strong> prints queued
        </div>
      </header>

      <div className="layout">
        <section className="card" aria-label="Create label">
          <h2 className="card__title">Design a label</h2>
          <p className="card__subtitle">Configure it, preview live, then add it to the queue.</p>

          <div className="preview">
            <div
              className={`label-tag ${size}`}
              style={{ ["--tag-color" as string]: color }}
            >
              <span className="label-tag__name">{name || "Label name"}</span>
              <span className="label-tag__text">{text || "Your text here"}</span>
              <span className="label-tag__qty">×{quantity}</span>
            </div>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                type="text"
                value={name}
                placeholder="e.g. Fragile"
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="field">
              <label htmlFor="text">Label text</label>
              <input
                id="text"
                type="text"
                value={text}
                placeholder="e.g. Handle With Care"
                onChange={(e) => setText(e.target.value)}
              />
            </div>

            <div className="field">
              <label>Color</label>
              <div className="swatches">
                {SWATCHES.map((swatch) => (
                  <button
                    key={swatch}
                    type="button"
                    className="swatch"
                    style={{ background: swatch }}
                    aria-label={`Use color ${swatch}`}
                    aria-pressed={color === swatch}
                    onClick={() => setColor(swatch)}
                  />
                ))}
              </div>
            </div>

            <div className="row">
              <div className="field">
                <label htmlFor="size">Size</label>
                <select
                  id="size"
                  value={size}
                  onChange={(e) => setSize(e.target.value as LabelSize)}
                >
                  {SIZES.map((s) => (
                    <option key={s} value={s}>
                      {s[0].toUpperCase() + s.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="quantity">Quantity</label>
                <input
                  id="quantity"
                  type="number"
                  min={1}
                  value={quantity}
                  onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                />
              </div>
            </div>

            {error ? <p className="error">{error}</p> : null}

            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Adding…" : "Add label to queue"}
            </button>
          </form>
        </section>

        <section className="card" aria-label="Label queue">
          <div className="section-head">
            <div>
              <h2 className="card__title">Label queue</h2>
              <p className="card__subtitle">Everything staged for printing.</p>
            </div>
            <span className="count">{loading ? "Loading…" : `${labels.length} total`}</span>
          </div>

          {!loading && labels.length === 0 ? (
            <div className="empty">No labels yet — design your first one on the left.</div>
          ) : (
            <div className="list">
              {labels.map((label) => (
                <div className="list-item" key={label.id}>
                  <span className="list-item__dot" style={{ background: label.color }} />
                  <div className="list-item__body">
                    <div className="list-item__name">{label.name}</div>
                    <div className="list-item__meta">
                      “{label.text}” · {label.size} · ×{label.quantity}
                    </div>
                  </div>
                  <span className="list-item__badge">{label.size}</span>
                  <button
                    className="icon-btn"
                    type="button"
                    onClick={() => handleDelete(label.id)}
                    aria-label={`Delete ${label.name}`}
                  >
                    Delete
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
