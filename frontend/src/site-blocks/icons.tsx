// Amenity icons (lucide-react, ISC licence). Keys are the "icons" list in blocks.json.
import {
  Accessibility, AirVent, Caravan, CarFront, Coffee, CookingPot, Croissant, Dumbbell, Eye, Flame, Laptop, Mountain, PawPrint,
  Sparkles, SquareParking, Trees, Tv, Umbrella, Users, WashingMachine, Waves, Wifi, type LucideIcon,
} from "lucide-react";

const MAP: Record<string, LucideIcon> = {
  pool: Waves, wifi: Wifi, kitchen: CookingPot, parking: SquareParking, ac: AirVent, breakfast: Croissant, pets: PawPrint,
  gym: Dumbbell, spa: Sparkles, bonfire: Flame, garden: Trees, view: Eye, beach: Umbrella, workspace: Laptop, tv: Tv,
  washer: WashingMachine, family: Users, accessible: Accessibility, caravan: Caravan, driver: CarFront, mountain: Mountain, coffee: Coffee,
};

export function AmenityIcon({ name }: { name: string }) {
  const Icon = MAP[name] || Sparkles;
  return <Icon aria-hidden="true" strokeWidth={1.6} />;
}
