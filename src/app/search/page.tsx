import { redirect } from "next/navigation";

/**
 * ChargePlus — Route /search Decision (Spec §55, §76):
 *
 * Decision: Recommended approach.
 * Rather than duplicating the complex station filtering, sorting, distance calculation,
 * and MapLibre map discovery logic in a separate redundant page, /search performs a zero-delay
 * server redirect to `/explore?focus=search`.
 *
 * ExploreClient automatically detects `focus=search` and focuses the search input on hydration,
 * enabling immediate zero-click search for signed-out and signed-in visitors alike while
 * preserving a single cohesive discovery workflow.
 */
export default function SearchPage() {
  redirect("/explore?focus=search");
}
