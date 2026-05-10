export interface VerdictDict {
  key: string;
  en_current: string;
  zh_current: string;
  verdict: "PASS" | "⚠️ SUGGEST" | "🔶 REVIEW" | "❌ FAIL";
  suggestion: string;
  reason: string;
  source: string;
}

export interface ReviewStats {
  total: number;
  PASS: number;
  SUGGEST: number;
  REVIEW: number;
  FAIL: number;
}

export interface ReviewReport {
  stats: ReviewStats;
  verdicts: VerdictDict[];
}

export const VERDICT_COLORS: Record<string, string> = {
  "❌ FAIL": "bg-red-100 text-red-800 border-red-300",
  "🔶 REVIEW": "bg-orange-100 text-orange-800 border-orange-300",
  "⚠️ SUGGEST": "bg-yellow-100 text-yellow-800 border-yellow-300",
  PASS: "bg-green-100 text-green-800 border-green-300",
};

export const VERDICT_BADGE: Record<string, string> = {
  "❌ FAIL": "bg-red-500",
  "🔶 REVIEW": "bg-orange-500",
  "⚠️ SUGGEST": "bg-yellow-500",
  PASS: "bg-green-500",
};

export const VERDICT_PRIORITY: Record<string, number> = {
  "❌ FAIL": 4,
  "🔶 REVIEW": 3,
  "⚠️ SUGGEST": 2,
  PASS: 1,
};
