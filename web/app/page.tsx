"use client";
import { useState } from "react";
import KpiGrid from "@/components/dashboard/KpiGrid";
import TrendPanel from "@/components/dashboard/TrendPanel";
import ItcMix from "@/components/dashboard/ItcMix";
import MatchSections from "@/components/dashboard/MatchSections";
import TopVendors from "@/components/dashboard/TopVendors";
import Insights from "@/components/dashboard/Insights";
import LayerStrip from "@/components/dashboard/LayerStrip";

export default function Overview() {
  const [focus, setFocus] = useState("purchase_total");
  return (
    <div className="space-y-5">
      <KpiGrid active={focus} onPick={setFocus} />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2"><TrendPanel focus={focus} /></div>
        <ItcMix />
      </div>
      <MatchSections />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2"><TopVendors compact /></div>
        <Insights />
      </div>
      <LayerStrip />
    </div>
  );
}
