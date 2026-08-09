import { NextResponse } from "next/server";
import { deleteLabel } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function DELETE(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const removed = await deleteLabel(id);
  if (!removed) {
    return NextResponse.json({ error: "Label not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
