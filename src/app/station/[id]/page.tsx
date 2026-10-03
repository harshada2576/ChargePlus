import { fetchStationById, fetchStations } from "@/data/stations";
import { StationDetail } from "./StationDetail";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const station = await fetchStationById(id);
  if (!station) return notFound();
  return <StationDetail station={station} />;
}

export async function generateStaticParams() {
  const stations = await fetchStations();
  return stations.map((s) => ({ id: s.id }));
}
