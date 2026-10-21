import { IntelligenceClient } from "./IntelligenceClient";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Station Intelligence & Data Mining | ChargePlus",
  description:
    "Spatial density clustering (DBSCAN), demand grouping (K-Means), chronological occupancy regression, and coverage gap analysis for Mumbai EV charging infrastructure.",
};

export default function Page() {
  return <IntelligenceClient />;
}
