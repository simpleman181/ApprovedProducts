export type Decision = "Recommended" | "Not recommended" | "Additional data requested" | "Other";

export interface CdscoRecord {
  id: string;
  drug: string;
  company: string;
  date: string | null; // YYYY-MM-DD, YYYY-MM or YYYY
  year: number | null;
  month: number | null;
  indication: string;
  recommendation: string;
  decision: Decision;
  therapy: string[];
  drugType: string;
  sourceUrl: string;
  /** "document" = record-specific file; "listing" = CDSCO listing filtered to this drug/period */
  linkKind: "document" | "listing";
  firstSeen: string; // YYYY-MM-DD, when this pipeline first saw the record
  quality?: string[];
}

export interface IndexFile {
  meta: { version: number; generatedAt: string; count: number; sample: boolean };
  records: CdscoRecord[];
}
