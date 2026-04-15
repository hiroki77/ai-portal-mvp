import { NextRequest, NextResponse } from "next/server";
import { searchHotels, getDistanceKm, estimateTaxiFare, estimateTaxiDuration } from "@/lib/mock-data";

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

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const location = searchParams.get("location") || "東京駅";
  const duration = parseInt(searchParams.get("duration") || "2");

  // Simulate network delay
  await new Promise((r) => setTimeout(r, 600));

  const coords = AREA_COORDS[location] || AREA_COORDS["東京駅"];
  const hotels = searchHotels(coords.lat, coords.lng, duration);

  const results = hotels.map((hotel) => {
    const distance = getDistanceKm(coords.lat, coords.lng, hotel.lat, hotel.lng);
    const taxiFare = estimateTaxiFare(distance);
    const taxiMinutes = estimateTaxiDuration(distance);
    const plan = hotel.plans.find((p) => p.duration === duration) || hotel.plans[0];

    return {
      ...hotel,
      distanceKm: Math.round(distance * 10) / 10,
      taxiMinutes,
      taxiFareOneWay: taxiFare,
      selectedPlan: plan,
      totalPrice: plan.price + taxiFare * 2,
      availableRooms: Math.floor(Math.random() * 5) + 1,
    };
  });

  return NextResponse.json({ hotels: results, location, duration });
}
