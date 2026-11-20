export const LAYER_META: Record<string, { n: number; color: string; bg: string; ring: string }> = {
  "Intake": { n: 1, color: "#1a73e8", bg: "#e8f0fe", ring: "#aecbfa" },
  "Normalize": { n: 2, color: "#5f6368", bg: "#f1f3f4", ring: "#dadce0" },
  "Match": { n: 3, color: "#9334e6", bg: "#f3e8fd", ring: "#d7aefb" },
  "Rule retrieval (RAG)": { n: 4, color: "#129eaf", bg: "#e4f7fb", ring: "#a2e1ec" },
  "ITC decision": { n: 5, color: "#e37400", bg: "#fef0dc", ring: "#fdc990" },
  "Tax and draft": { n: 6, color: "#188038", bg: "#e6f4ea", ring: "#a8dab5" },
};
export const layerMeta = (name: string) => LAYER_META[name] ?? { n: 0, color: "#5f6368", bg: "#f1f3f4", ring: "#dadce0" };
