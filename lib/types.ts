export type LabelSize = "small" | "medium" | "large";

export interface Label {
  id: string;
  name: string;
  text: string;
  color: string;
  size: LabelSize;
  quantity: number;
  createdAt: string;
}

export type NewLabel = Omit<Label, "id" | "createdAt">;

export const LABEL_SIZES: LabelSize[] = ["small", "medium", "large"];

export function isLabelSize(value: unknown): value is LabelSize {
  return typeof value === "string" && (LABEL_SIZES as string[]).includes(value);
}
