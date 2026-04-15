export interface Hotel {
  id: string;
  name: string;
  nameEn: string;
  address: string;
  area: string;
  lat: number;
  lng: number;
  imageUrl: string;
  rating: number;
  amenities: string[];
  plans: NapPlan[];
}

export interface NapPlan {
  id: string;
  duration: number; // hours
  label: string;
  price: number; // JPY
  roomType: string;
  description: string;
}

export interface Booking {
  id: string;
  status: BookingStatus;
  hotel: Hotel;
  plan: NapPlan;
  pickupLocation: string;
  pickupLat: number;
  pickupLng: number;
  taxiArrivalMinutes: number;
  checkInTime: string;
  checkOutTime: string;
  returnTaxiTime: string;
  totalPrice: number;
  taxiPriceEstimate: number;
  createdAt: string;
  timeline: TimelineEvent[];
}

export type BookingStatus =
  | "taxi_dispatched"
  | "taxi_arriving"
  | "heading_to_hotel"
  | "checked_in"
  | "napping"
  | "waking_up"
  | "return_taxi_dispatched"
  | "heading_back"
  | "completed";

export interface TimelineEvent {
  time: string;
  label: string;
  status: "done" | "current" | "upcoming";
  icon: string;
}

export interface TaxiEstimate {
  distanceKm: number;
  durationMinutes: number;
  priceEstimate: number;
}
