export interface Project {
  id: string;
  title: string;
  status: string;
}

export interface BibleVersionSummary {
  version: number;
  status: string;
  source: string;
  sha256: string;
  created_at: string;
  approved_at: string | null;
}

export interface BibleVersion extends BibleVersionSummary {
  body: string;
}

export interface ReferenceAsset {
  id: string;
  kind: string;
  status: string;
  role: string | null;
  view: string | null;
  pose: string | null;
  expression: string | null;
  width: number | null;
  height: number | null;
  mime_type: string | null;
  sha256: string;
  has_alpha: boolean | null;
  approved_at: string | null;
  created_at: string;
  content_url: string;
}

export interface CharacterSummary {
  id: string;
  slug: string;
  name: string;
  kind: string;
  status: string;
  description: string | null;
  reference_count: number;
  approved_reference_count: number;
  bible_version_count: number;
  latest_bible_version: number | null;
  latest_bible_status: string | null;
}

export interface CharacterDetail extends CharacterSummary {
  bible_versions: BibleVersionSummary[];
}

export interface LocationSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  reference_count: number;
}

export interface PropSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  reference_count: number;
}

export interface ReferenceFilters {
  status: string;
  view: string;
  pose: string;
}
