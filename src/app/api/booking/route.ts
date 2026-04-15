import { NextRequest, NextResponse } from "next/server";
import { createMockBooking } from "@/lib/mock-data";

// In-memory booking store (fine for MVP demo)
const bookings = new Map<string, ReturnType<typeof createMockBooking>>();

export { bookings };

const AREA_COORDS: Record<string, { lat: number; lng: number }> = {
  "東京駅": { lat: 35.6812, lng: 139.7671 },
  "新宿駅": { lat: 35.6896, lng: 139.7006 },
  "渋谷駅": { lat: 35.6580, lng: 139.7016 },
  "品川駅": { lat: 35.6284, lng: 139.7387 },
  "六本木": { lat: 35.6627, lng: 139.7307 },
  "銀座": { lat: 35.6717, lng: 139.7659 },
  "池袋駅": { lat: 35.7295, lng: 139.7109 },
  "秋葉原駅": { lat: 35.6984, lng: 139.7731 },
  "赤坂": { lat: 35.6742, lng: 139.7371 },
  "丸の内": { lat: 35.6819, lng: 139.7649 },
};

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { hotelId, planId, location } = body;

  const coords = AREA_COORDS[location] || AREA_COORDS["東京駅"];
  const booking = createMockBooking(
    hotelId,
    planId,
    location,
    coords.lat,
    coords.lng
  );

  bookings.set(booking.id, booking);

  return NextResponse.json(booking);
}
