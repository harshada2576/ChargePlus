import { STATIONS, getStation } from "@/data/stations";
import { StationDetail } from "./StationDetail";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const station = getStation(id);
  if (!station) return notFound();
  return <StationDetail station={station} />;
}

export function generateStaticParams() {
  return STATIONS.map((s) => ({ id: s.id }));
}
