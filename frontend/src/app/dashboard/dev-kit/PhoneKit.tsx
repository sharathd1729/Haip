"use client";
// Dev-kit gallery section for the phone primitives (rows, chip row, bottom sheet, one-line summary, floating button), with
// worst-case data. Check it at 375px: nothing may scroll sideways and every action is 44px.
import { useState } from "react";
import { IndianRupee, MessageCircle, Phone, UserPlus, ExternalLink } from "@/lib/icons";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import {
  BottomSheet, Card, CardBody, CardHeader, ChipRow, CompactRow, Fab, OneLineSummary, RowAction, RowList, RowSection, RowTag,
  SheetActions, SheetLine, sheetActionCls,
} from "@/components/ui/kit";

export function PhoneKit() {
  const [chip, setChip] = useState("mine");
  const [sheet, setSheet] = useState(false);
  const [fabHits, setFabHits] = useState(0);
  return (
    <Card>
      <CardHeader title="Phone primitives" description="CompactRow, ChipRow, BottomSheet, OneLineSummary, Fab. Check at 375px." />
      <CardBody className="grid gap-4">
        <ChipRow label="Whose work" value={chip} onChange={setChip} onFilters={() => setSheet(true)} filterCount={2}
          items={[{ value: "mine", label: "Mine", count: 7 }, { value: "team", label: "Team", count: 1234 }, { value: "callbacks", label: "Call backs", count: 0 }, { value: "new", label: "New leads with a very long label" }]} />
        <RowSection title="Call now" count={3}>
          <RowList label="Call now">
            <CompactRow avatar={<GuestAvatar name="Priya Subramaniam-Venkataraghavan Iyer" />} title="Priya Subramaniam-Venkataraghavan Iyer · Kerala, 3-9 Jan"
              subtitle="Asked for a call back · 4 adults + 2 children · birthday trip with a very long note" meta="12d late" metaTone="danger"
              onClick={() => setSheet(true)} actions={<RowAction icon={Phone} label="Call Priya" primary onClick={() => undefined} />} />
            <CompactRow avatar={<GuestAvatar name="Al" />} title="Al" subtitle="Missed call, no answer yet" meta="5h late" metaTone="warning"
              extra={<><RowTag tone="warning">unassigned</RowTag><RowTag tone="brand">Active</RowTag></>}
              onClick={() => setSheet(true)} actions={<><RowAction icon={UserPlus} label="Assign" onClick={() => undefined} /><RowAction icon={Phone} label="Call" primary onClick={() => undefined} /></>} />
            <CompactRow avatar={<GuestAvatar phone="+919800000001" />} title="+91 98000 00001" subtitle="Shared number on Instagram" meta="due in 10m" metaSub="7:41 pm" href="#kit" />
          </RowList>
        </RowSection>
        <RowList label="Empty example"><li className="px-4 py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">Nobody is waiting.</li></RowList>
        <OneLineSummary text="Wants a Goa trip for 4 adults on 26 Nov; Goa is not offered, so suggest Western Ghats to the Sea. Asked about the price twice." />
        <OneLineSummary text="Wants Coorg 3 days" />
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Floating button taps: {fabHits} (bottom right on phones only)</p>
        <Fab label="New lead" onClick={() => setFabHits(n => n + 1)} />
        <BottomSheet open={sheet} onOpenChange={setSheet} title="Anita · Coorg, 30-31 Oct" description="Ratha 1 · 4 adults · Mysuru and Coorg"
          footer={<SheetActions>
            <button type="button" className={sheetActionCls(true)}><IndianRupee size={18} />Collect</button>
            <button type="button" className={sheetActionCls()}><MessageCircle size={18} />WhatsApp</button>
            <a href="#kit" className={sheetActionCls()}><ExternalLink size={18} />Full page</a>
          </SheetActions>}>
          <SheetLine label="Total" value="₹12,34,56,789" strong />
          <SheetLine label="Paid" value="₹71,700" />
          <SheetLine label="Still due before trip" value="₹5,000" tone="due" />
        </BottomSheet>
      </CardBody>
    </Card>
  );
}
