import { useState } from "react";

import { api } from "../api/client";
import type { ReferenceAsset } from "../api/types";

export interface ReferenceReview {
  pendingId: string | null;
  actionError: string | null;
  /** Утверждение/отклонение референса; null — запрос не удался. */
  review: (
    asset: ReferenceAsset,
    action: "approve" | "reject",
  ) => Promise<ReferenceAsset | null>;
}

export function useReferenceReview(): ReferenceReview {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function review(
    asset: ReferenceAsset,
    action: "approve" | "reject",
  ): Promise<ReferenceAsset | null> {
    setPendingId(asset.id);
    setActionError(null);
    try {
      return action === "approve" ? await api.approve(asset.id) : await api.reject(asset.id);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
      return null;
    } finally {
      setPendingId(null);
    }
  }

  return { pendingId, actionError, review };
}
