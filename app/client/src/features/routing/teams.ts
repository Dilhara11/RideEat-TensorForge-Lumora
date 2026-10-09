// Visual identity for the fixed routing destinations (the team names come from the contract table in lib/tickets).

import type { IconName } from "../../components/icons";
import { TEAMS } from "../../lib/tickets";
import type { Channel } from "../../lib/types";

const TEAM_ICON: Record<string, IconName> = {
  "Payments & Refunds": "card",
  "Ride Operations": "car",
  "Lost & Found": "search",
  "Food Operations": "bag",
  "Delivery Operations": "truck",
  "Restaurant Quality": "utensils",
  "Account Services": "user",
  "Trust & Safety": "shield",
  "Tech Support": "wrench",
  "Front-line Support": "headset",
  "Auto-close / Spam Filter": "ban",
};

/** Example: teamIcon("Lost & Found") -> "search". Unknown teams get a generic inbox. */
export const teamIcon = (team: string): IconName => TEAM_ICON[team] ?? "inbox";

export const CHANNEL_ICON: Record<Channel, IconName> = { chat: "chat", email: "mail", call_transcript: "phone" };

export const SPAM_TEAM = "Auto-close / Spam Filter";

/** Every destination on the dispatch board, in contract order. */
export const DESTINATIONS: string[] = TEAMS;
