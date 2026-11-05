import { IntelligenceClient } from "./IntelligenceClient";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Station Intelligence & Data Mining | ChargePlus",
  description:
    "Spatial density clustering (DBSCAN), demand grouping (K-Means), chronological occupancy regression, and station isolation analysis across India's EV charging network snapshot.",
};

export default function Page() {
  return <IntelligenceClient />;
}
