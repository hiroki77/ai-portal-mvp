import { NextRequest, NextResponse } from "next/server";

const TAXI_COMPANIES = [
  { name: "日本交通", plate: "品川 500 あ 12-34" },
  { name: "大和自動車", plate: "練馬 500 い 56-78" },
  { name: "帝都自動車", plate: "足立 500 う 90-12" },
  { name: "国際自動車", plate: "世田谷 500 え 34-56" },
];

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { bookingId, type } = body;

  await new Promise((r) => setTimeout(r, 300));

  const taxi = TAXI_COMPANIES[Math.floor(Math.random() * TAXI_COMPANIES.length)];

  return NextResponse.json({
    bookingId,
    type,
    taxi: {
      company: taxi.name,
      plateNumber: taxi.plate,
      estimatedArrival: Math.floor(Math.random() * 5) + 3,
      driverName: "ドライバー",
    },
    dispatched: true,
  });
}
