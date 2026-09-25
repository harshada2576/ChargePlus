import { SimplePage } from "@/components/SimplePage";
export default function Page() {
  return (
    <SimplePage title="About ChargePlus">
      <p>
        ChargePlus helps EV drivers find the right charger before they reach the queue. We are starting
        with Mumbai and expanding across India.
      </p>
      <p className="mt-3">
        Our pilot focuses on giving you clear, useful information about nearby stations — including
        current availability, connector type, charging speed and price — so you can plan your charge with
        confidence.
      </p>
    </SimplePage>
  );
}
