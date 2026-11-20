"use client";
import TopVendors from "@/components/dashboard/TopVendors";

export default function VendorsPage() {
  return (
    <div className="space-y-5">
      <p className="text-sm text-ink-500 max-w-3xl">Vendors decide how much of your credit you can claim. Sort by at-risk credit to see who to call first, widen the window to find vendors that keep missing their filings, and open a vendor for the six month trend and its invoices.</p>
      <TopVendors />
    </div>
  );
}
