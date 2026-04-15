import { Hotel, Booking, TimelineEvent } from "./types";

export const MOCK_HOTELS: Hotel[] = [
  {
    id: "hotel-1",
    name: "レムプラス銀座",
    nameEn: "remm plus Ginza",
    address: "東京都中央区銀座3-5-13",
    area: "銀座",
    lat: 35.6717,
    lng: 139.7659,
    imageUrl: "/hotels/ginza.jpg",
    rating: 4.5,
    amenities: ["Wi-Fi", "シャワー", "アメニティ", "USB充電", "遮光カーテン"],
    plans: [
      {
        id: "plan-1a",
        duration: 1,
        label: "クイック仮眠 1時間",
        price: 2500,
        roomType: "シングル",
        description: "サッと休んでリフレッシュ",
      },
      {
        id: "plan-1b",
        duration: 2,
        label: "しっかり仮眠 2時間",
        price: 3800,
        roomType: "シングル",
        description: "1サイクルの睡眠でスッキリ",
      },
      {
        id: "plan-1c",
        duration: 3,
        label: "ディープレスト 3時間",
        price: 4800,
        roomType: "ダブル",
        description: "深い休息で完全回復",
      },
    ],
  },
  {
    id: "hotel-2",
    name: "ナインアワーズ赤坂",
    nameEn: "nine hours Akasaka",
    address: "東京都港区赤坂3-14-3",
    area: "赤坂",
    lat: 35.6742,
    lng: 139.7371,
    imageUrl: "/hotels/akasaka.jpg",
    rating: 4.2,
    amenities: ["Wi-Fi", "シャワー", "ロッカー", "アイマスク", "耳栓"],
    plans: [
      {
        id: "plan-2a",
        duration: 1,
        label: "クイック仮眠 1時間",
        price: 1800,
        roomType: "カプセル",
        description: "都心の静かな空間で短時間休憩",
      },
      {
        id: "plan-2b",
        duration: 2,
        label: "しっかり仮眠 2時間",
        price: 2800,
        roomType: "カプセル",
        description: "洗練された空間でしっかり睡眠",
      },
      {
        id: "plan-2c",
        duration: 3,
        label: "ディープレスト 3時間",
        price: 3500,
        roomType: "カプセル",
        description: "最高の仮眠体験",
      },
    ],
  },
  {
    id: "hotel-3",
    name: "ホテルグレイスリー新宿",
    nameEn: "Hotel Gracery Shinjuku",
    address: "東京都新宿区歌舞伎町1-19-1",
    area: "新宿",
    lat: 35.6938,
    lng: 139.7013,
    imageUrl: "/hotels/shinjuku.jpg",
    rating: 4.3,
    amenities: ["Wi-Fi", "バス", "アメニティ", "コーヒー", "遮光カーテン"],
    plans: [
      {
        id: "plan-3a",
        duration: 1,
        label: "クイック仮眠 1時間",
        price: 2800,
        roomType: "シングル",
        description: "歌舞伎町の好立地で手軽に休憩",
      },
      {
        id: "plan-3b",
        duration: 2,
        label: "しっかり仮眠 2時間",
        price: 4200,
        roomType: "シングル",
        description: "しっかり休んで午後に備える",
      },
      {
        id: "plan-3c",
        duration: 3,
        label: "ディープレスト 3時間",
        price: 5500,
        roomType: "ダブル",
        description: "広い部屋で贅沢な仮眠",
      },
    ],
  },
  {
    id: "hotel-4",
    name: "ドーミーインPREMIUM渋谷神宮前",
    nameEn: "Dormy Inn PREMIUM Shibuya",
    address: "東京都渋谷区神宮前6-24-4",
    area: "渋谷",
    lat: 35.6654,
    lng: 139.7054,
    imageUrl: "/hotels/shibuya.jpg",
    rating: 4.6,
    amenities: ["Wi-Fi", "大浴場", "アメニティ", "マッサージチェア", "遮光カーテン"],
    plans: [
      {
        id: "plan-4a",
        duration: 1,
        label: "クイック仮眠 1時間",
        price: 3000,
        roomType: "シングル",
        description: "大浴場付きでリフレッシュ",
      },
      {
        id: "plan-4b",
        duration: 2,
        label: "しっかり仮眠 2時間",
        price: 4500,
        roomType: "シングル",
        description: "お風呂+仮眠の贅沢プラン",
      },
      {
        id: "plan-4c",
        duration: 3,
        label: "ディープレスト 3時間",
        price: 5800,
        roomType: "ダブル",
        description: "大浴場で癒されてから深い眠り",
      },
    ],
  },
  {
    id: "hotel-5",
    name: "相鉄フレッサイン東京六本木",
    nameEn: "Sotetsu Fresa Inn Tokyo Roppongi",
    address: "東京都港区六本木7-8-5",
    area: "六本木",
    lat: 35.6627,
    lng: 139.7307,
    imageUrl: "/hotels/roppongi.jpg",
    rating: 4.1,
    amenities: ["Wi-Fi", "シャワー", "アメニティ", "デスク", "遮光カーテン"],
    plans: [
      {
        id: "plan-5a",
        duration: 1,
        label: "クイック仮眠 1時間",
        price: 2200,
        roomType: "シングル",
        description: "六本木で気軽に仮眠",
      },
      {
        id: "plan-5b",
        duration: 2,
        label: "しっかり仮眠 2時間",
        price: 3500,
        roomType: "シングル",
        description: "清潔な部屋でしっかり休憩",
      },
      {
        id: "plan-5c",
        duration: 3,
        label: "ディープレスト 3時間",
        price: 4500,
        roomType: "ダブル",
        description: "ゆったり空間で深い休息",
      },
    ],
  },
];

export function searchHotels(lat: number, lng: number, duration?: number): Hotel[] {
  return MOCK_HOTELS.map((hotel) => {
    const distance = getDistanceKm(lat, lng, hotel.lat, hotel.lng);
    return { ...hotel, distance };
  })
    .sort((a, b) => (a as Hotel & { distance: number }).distance - (b as Hotel & { distance: number }).distance)
    .map(({ ...hotel }) => hotel);
}

export function getDistanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) *
      Math.sin(dLng / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export function estimateTaxiFare(distanceKm: number): number {
  // Tokyo taxi fare estimation
  const baseFare = 500; // initial fare
  const perKmRate = 300; // ~300 yen per km
  return Math.round((baseFare + distanceKm * perKmRate) / 100) * 100;
}

export function estimateTaxiDuration(distanceKm: number): number {
  // Rough estimate: 15-20km/h average in Tokyo
  return Math.max(5, Math.round((distanceKm / 18) * 60));
}

export function createMockBooking(
  hotelId: string,
  planId: string,
  pickupLocation: string,
  pickupLat: number,
  pickupLng: number
): Booking {
  const hotel = MOCK_HOTELS.find((h) => h.id === hotelId)!;
  const plan = hotel.plans.find((p) => p.id === planId)!;
  const distance = getDistanceKm(pickupLat, pickupLng, hotel.lat, hotel.lng);
  const taxiDuration = estimateTaxiDuration(distance);
  const taxiFare = estimateTaxiFare(distance);

  const now = new Date();
  const taxiArrival = new Date(now.getTime() + 5 * 60000);
  const hotelArrival = new Date(taxiArrival.getTime() + taxiDuration * 60000);
  const checkOut = new Date(hotelArrival.getTime() + plan.duration * 3600000);
  const returnTaxi = new Date(checkOut.getTime() + 5 * 60000);
  const back = new Date(returnTaxi.getTime() + taxiDuration * 60000);

  const fmt = (d: Date) =>
    d.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });

  const timeline: TimelineEvent[] = [
    { time: fmt(now), label: "予約確定", status: "done", icon: "check" },
    { time: fmt(taxiArrival), label: "タクシー到着", status: "current", icon: "taxi" },
    { time: fmt(hotelArrival), label: "ホテル到着・チェックイン", status: "upcoming", icon: "hotel" },
    { time: fmt(checkOut), label: "チェックアウト", status: "upcoming", icon: "alarm" },
    { time: fmt(returnTaxi), label: "お迎えタクシー到着", status: "upcoming", icon: "taxi" },
    { time: fmt(back), label: "元の場所に到着", status: "upcoming", icon: "flag" },
  ];

  return {
    id: `NP-${Date.now().toString(36).toUpperCase()}`,
    status: "taxi_dispatched",
    hotel,
    plan,
    pickupLocation,
    pickupLat,
    pickupLng,
    taxiArrivalMinutes: 5,
    checkInTime: fmt(hotelArrival),
    checkOutTime: fmt(checkOut),
    returnTaxiTime: fmt(returnTaxi),
    totalPrice: plan.price + taxiFare * 2,
    taxiPriceEstimate: taxiFare * 2,
    createdAt: now.toISOString(),
    timeline,
  };
}
