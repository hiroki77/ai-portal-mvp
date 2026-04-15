import { NextRequest, NextResponse } from "next/server";
import { bookings } from "../route";
import { BookingStatus } from "@/lib/types";

// Auto-progress booking status based on elapsed time (compressed for demo)
const STATUS_PROGRESSION: { after: number; status: BookingStatus; label: string }[] = [
  { after: 0, status: "taxi_dispatched", label: "タクシーを手配しました" },
  { after: 15, status: "taxi_arriving", label: "タクシーがまもなく到着します" },
  { after: 30, status: "heading_to_hotel", label: "ホテルに向かっています" },
  { after: 60, status: "checked_in", label: "チェックイン完了" },
  { after: 75, status: "napping", label: "おやすみなさい..." },
  { after: 120, status: "waking_up", label: "おはようございます！" },
  { after: 140, status: "return_taxi_dispatched", label: "お迎えタクシーを手配しました" },
  { after: 160, status: "heading_back", label: "元の場所に向かっています" },
  { after: 200, status: "completed", label: "お疲れさまでした！" },
];

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const booking = bookings.get(id);

  if (!booking) {
    return NextResponse.json(
      { error: "予約が見つかりませんでした" },
      { status: 404 }
    );
  }

  // Calculate elapsed seconds since booking creation
  const elapsed = (Date.now() - new Date(booking.createdAt).getTime()) / 1000;

  // Find current status based on elapsed time
  let currentStatus = STATUS_PROGRESSION[0];
  for (const s of STATUS_PROGRESSION) {
    if (elapsed >= s.after) {
      currentStatus = s;
    }
  }

  // Update booking status
  booking.status = currentStatus.status;

  // Update timeline statuses
  const statusOrder: BookingStatus[] = [
    "taxi_dispatched",
    "taxi_arriving",
    "heading_to_hotel",
    "checked_in",
    "napping",
    "waking_up",
    "return_taxi_dispatched",
    "heading_back",
    "completed",
  ];
  const currentIndex = statusOrder.indexOf(currentStatus.status);

  const updatedTimeline = booking.timeline.map((event, i) => ({
    ...event,
    status: i < currentIndex ? "done" as const :
            i === currentIndex ? "current" as const :
            "upcoming" as const,
  }));

  return NextResponse.json({
    ...booking,
    timeline: updatedTimeline,
    statusLabel: currentStatus.label,
  });
}
