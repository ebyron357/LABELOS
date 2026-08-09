import { NextResponse } from "next/server";
import { createLabel, listLabels } from "@/lib/store";
import { isLabelSize, type NewLabel } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET() {
  const labels = await listLabels();
  return NextResponse.json({ labels });
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const data = body as Record<string, unknown>;
  const name = typeof data.name === "string" ? data.name.trim() : "";
  const text = typeof data.text === "string" ? data.text.trim() : "";
  const color = typeof data.color === "string" ? data.color : "#3b82f6";
  const size = isLabelSize(data.size) ? data.size : "medium";
  const quantity =
    typeof data.quantity === "number" && Number.isFinite(data.quantity)
      ? Math.max(1, Math.floor(data.quantity))
      : 1;

  if (!name) {
    return NextResponse.json({ error: "A label name is required" }, { status: 400 });
  }
  if (!text) {
    return NextResponse.json({ error: "Label text is required" }, { status: 400 });
  }

  const payload: NewLabel = { name, text, color, size, quantity };
  const label = await createLabel(payload);
  return NextResponse.json({ label }, { status: 201 });
}
