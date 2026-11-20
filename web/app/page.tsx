"use client";
import KpiCards from "@/components/dashboard/KpiCards";
import TrendPanel from "@/components/dashboard/TrendPanel";
import TopVendors from "@/components/dashboard/TopVendors";

export default function Overview() {
  return (
    <div className="space-y-5">
      <KpiCards />
      <TrendPanel />
      <TopVendors />
    </div>
  );
}
