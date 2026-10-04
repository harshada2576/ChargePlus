import { fetchStationById, fetchStations } from "@/data/stations";
import { listApprovedReviews } from "@/lib/reviews";
import { supabase } from "@/lib/supabase";
import { StationDetail } from "./StationDetail";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const station = await fetchStationById(id);
  if (!station) return notFound();
  // Approved public reviews only (sanitized view); failures leave the
  // section honestly empty rather than blocking the canonical record.
  const reviews = await listApprovedReviews(supabase, station.id).catch(() => []);
  return <StationDetail station={station} reviews={reviews} />;
}

export async function generateStaticParams() {
  const stations = await fetchStations();
  return stations.map((s) => ({ id: s.id }));
}
