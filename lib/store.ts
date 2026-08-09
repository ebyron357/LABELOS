import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { Label, NewLabel } from "./types";

// Lightweight JSON-file persistence. The filesystem is ephemeral in Cloud
// Agent VMs, which is fine for local development: state survives across
// requests and hot reloads within a single running dev server.
const DATA_DIR = path.join(process.cwd(), ".data");
const DATA_FILE = path.join(DATA_DIR, "labels.json");

const SEED: Label[] = [
  {
    id: "seed-welcome",
    name: "Welcome",
    text: "Fragile — Handle With Care",
    color: "#ef4444",
    size: "medium",
    quantity: 12,
    createdAt: new Date("2026-01-01T00:00:00.000Z").toISOString(),
  },
  {
    id: "seed-shipping",
    name: "Shipping",
    text: "Priority Mail",
    color: "#3b82f6",
    size: "large",
    quantity: 48,
    createdAt: new Date("2026-01-02T00:00:00.000Z").toISOString(),
  },
];

async function ensureFile(): Promise<void> {
  await fs.mkdir(DATA_DIR, { recursive: true });
  try {
    await fs.access(DATA_FILE);
  } catch {
    await fs.writeFile(DATA_FILE, JSON.stringify(SEED, null, 2), "utf8");
  }
}

async function readAll(): Promise<Label[]> {
  await ensureFile();
  const raw = await fs.readFile(DATA_FILE, "utf8");
  try {
    const parsed = JSON.parse(raw) as Label[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function writeAll(labels: Label[]): Promise<void> {
  await ensureFile();
  await fs.writeFile(DATA_FILE, JSON.stringify(labels, null, 2), "utf8");
}

export async function listLabels(): Promise<Label[]> {
  const labels = await readAll();
  return [...labels].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function createLabel(input: NewLabel): Promise<Label> {
  const labels = await readAll();
  const label: Label = {
    ...input,
    id: randomUUID(),
    createdAt: new Date().toISOString(),
  };
  labels.push(label);
  await writeAll(labels);
  return label;
}

export async function deleteLabel(id: string): Promise<boolean> {
  const labels = await readAll();
  const next = labels.filter((label) => label.id !== id);
  if (next.length === labels.length) {
    return false;
  }
  await writeAll(next);
  return true;
}
