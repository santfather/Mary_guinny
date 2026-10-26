import type { ReferenceAsset } from "../api/types";
import { ReferenceCard } from "./ReferenceCard";

interface ReferenceGridProps {
  assets: ReferenceAsset[];
  pendingId: string | null;
  onOpen: (asset: ReferenceAsset) => void;
  onApprove: (asset: ReferenceAsset) => void;
  onReject: (asset: ReferenceAsset) => void;
}

export function ReferenceGrid({
  assets,
  pendingId,
  onOpen,
  onApprove,
  onReject,
}: ReferenceGridProps) {
  return (
    <div className="grid">
      {assets.map((asset) => (
        <ReferenceCard
          key={asset.id}
          asset={asset}
          pending={pendingId === asset.id}
          onOpen={onOpen}
          onApprove={onApprove}
          onReject={onReject}
        />
      ))}
    </div>
  );
}
