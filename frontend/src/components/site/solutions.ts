/* Content for the solutions pages, taken from the approved mockup (make_sol.py). One entry per property type. */
export type ChatLine = ["g" | "h", string, string] | ["s", string];
export type Solution = { label: string; icon: string; biz: string; h1: [string, string]; lead: string; chat: ChatLine[];
  qs: [string, string][]; stops: [string, string][]; feats: [string, string][] };

export const SOLUTIONS = {
  "villas": {
    "label": "Villas",
    "icon": "HomeModernIcon",
    "biz": "Nila Villas",
    "h1": [
      "Every villa guest, ",
      "answered."
    ],
    "lead": "Pool, pets, guest count, dates. HAIP answers on WhatsApp and Instagram, takes the advance and gets the villa ready.",
    "chat": [
      [
        "g",
        "Hi! Is the villa free 20 to 22 Nov? We are 8 adults and a dog.",
        "10:42 PM"
      ],
      [
        "h",
        "It is. The villa sleeps 8 and pets are welcome. Shall I hold it and send the advance link?",
        "10:42 PM"
      ],
      [
        "g",
        "Yes please",
        "10:43 PM"
      ],
      [
        "s",
        "₹24,300 advance paid on Razorpay"
      ],
      [
        "h",
        "All set! Check-in is at 1 PM. Ravi, your caretaker, will meet you at the gate.",
        "10:44 PM"
      ]
    ],
    "qs": [
      [
        "Is the pool private?",
        "Yes. The pool is only for your group."
      ],
      [
        "Can we bring our dog?",
        "Yes, pets are welcome. Just tell us the size."
      ],
      [
        "Is there a cook?",
        "Yes. A cook is available, meals charged per day."
      ],
      [
        "What time is check-in?",
        "1 PM. Earlier if the villa is free."
      ]
    ],
    "stops": [
      [
        "Enquiry",
        "Answered in seconds, day or night."
      ],
      [
        "Quote",
        "Whole villa price for their dates."
      ],
      [
        "Advance",
        "Razorpay link, paid right in the chat."
      ],
      [
        "Ready",
        "Your caretaker ticks the welcome checklist."
      ],
      [
        "Check-out",
        "Inspection done, deposit returned."
      ]
    ],
    "feats": [
      [
        "Pool, pets and house rules",
        "Set your rules once. Every answer follows them."
      ],
      [
        "Deposits, held and returned",
        "The security deposit sits on the same booking and is never counted as revenue."
      ],
      [
        "Your caretaker, on WhatsApp",
        "Jobs and guest problems reach the right person. Nothing to install."
      ],
      [
        "Calendars in step",
        "Dates booked here are blocked on Airbnb and Booking.com through iCal."
      ]
    ]
  },
  "resorts": {
    "label": "Resorts",
    "icon": "BuildingOffice2Icon",
    "biz": "Kadal Resort",
    "h1": [
      "Busy weekends. ",
      "One calm desk."
    ],
    "lead": "Weddings, groups and peak dates. HAIP sorts every enquiry and hands the big ones to the right person on your team.",
    "chat": [
      [
        "g",
        "Hi, we need 12 rooms for a wedding on 14 Dec.",
        "11:05 AM"
      ],
      [
        "h",
        "Congratulations! I have passed this to Priya, who looks after weddings. She will call you within the hour.",
        "11:05 AM"
      ],
      [
        "s",
        "Group enquiry, 12 rooms · given to Priya"
      ],
      [
        "h",
        "Hi, Priya here. Sending you our wedding packages now.",
        "11:18 AM"
      ]
    ],
    "qs": [
      [
        "Rooms free on 31 Dec?",
        "We have 3 left. Shall I hold one for you?"
      ],
      [
        "Is breakfast included?",
        "Yes, with every room."
      ],
      [
        "Can we book the spa?",
        "Yes. Add it now or at check-in."
      ],
      [
        "Is there a kids pool?",
        "Yes, open from 8 AM to 7 PM."
      ]
    ],
    "stops": [
      [
        "Enquiry",
        "Every chat and call in one place."
      ],
      [
        "Right person",
        "Groups and events go to who handles them."
      ],
      [
        "Quote",
        "Rooms, meals and add-ons in one link."
      ],
      [
        "Advance",
        "Paid online, dates held on every channel."
      ],
      [
        "Stay",
        "Guest requests reach the team on duty."
      ]
    ],
    "feats": [
      [
        "Group and event enquiries",
        "Big enquiries reach the right person first, with the whole chat attached."
      ],
      [
        "Peak dates, no double booking",
        "One calendar for every room and channel."
      ],
      [
        "Add-ons guests actually buy",
        "Spa, meals and transfers offered by link, paid before arrival."
      ],
      [
        "Every call checked",
        "Calls recorded and scored, so promises are kept."
      ]
    ]
  },
  "hotels": {
    "label": "Hotels",
    "icon": "BuildingOffice2Icon",
    "biz": "Hotel Saffron",
    "h1": [
      "More direct bookings. ",
      "Fewer missed calls."
    ],
    "lead": "Answer travellers and travel agents on WhatsApp, call back every missed call and send quotes from your own rate card.",
    "chat": [
      [
        "g",
        "Need 6 rooms for Friday. Agent rate please.",
        "4:12 PM"
      ],
      [
        "h",
        "Agent rate applied: ₹3,200 a night for 6 rooms. Shall I send the quote?",
        "4:12 PM"
      ],
      [
        "g",
        "Yes, send it",
        "4:13 PM"
      ],
      [
        "s",
        "Quote sent · follow up on Thursday"
      ]
    ],
    "qs": [
      [
        "Airport pickup?",
        "Yes, ₹900 one way. Shall I book it?"
      ],
      [
        "Is parking free?",
        "Yes, free for hotel guests."
      ],
      [
        "Room for tonight?",
        "Yes, 2 rooms left. Want me to hold one?"
      ],
      [
        "Early check-in?",
        "From 10 AM when the room is ready."
      ]
    ],
    "stops": [
      [
        "Enquiry",
        "WhatsApp, calls and Instagram together."
      ],
      [
        "Rate",
        "Agent or direct rate, applied automatically."
      ],
      [
        "Quote",
        "Sent in the chat, with a follow-up set."
      ],
      [
        "Paid",
        "Payment link, receipt sent on its own."
      ],
      [
        "Check-out",
        "Bill settled, review asked for."
      ]
    ],
    "feats": [
      [
        "Travel agent rates",
        "Agents get their own rates every time, from your rate card."
      ],
      [
        "Missed calls called back",
        "Every missed call becomes a callback with a reminder."
      ],
      [
        "Front desk, one inbox",
        "WhatsApp, Instagram and calls in one list your whole team can see."
      ],
      [
        "Payments and invoices",
        "Links, receipts and invoices on the booking."
      ]
    ]
  },
  "caravans": {
    "label": "Caravans",
    "icon": "MapPinIcon",
    "biz": "Roam Caravans",
    "h1": [
      "Every trip, ",
      "DM to drop-off."
    ],
    "lead": "Routes, vehicles, add-ons and payments. HAIP books the trip, picks the free vehicle and keeps your crew in the loop.",
    "chat": [
      [
        "g",
        "Caravan for 3 days from 20 Nov? We are 4.",
        "9:30 AM"
      ],
      [
        "h",
        "Yes! Vehicle 2 is free from 20 to 22 Nov. Shall I share the routes?",
        "9:30 AM"
      ],
      [
        "s",
        "Vehicle 2 held for 20 to 22 Nov"
      ],
      [
        "g",
        "Yes, the hills route please",
        "9:32 AM"
      ],
      [
        "h",
        "Great choice. Here is the plan and the advance link.",
        "9:32 AM"
      ]
    ],
    "qs": [
      [
        "How many can sleep?",
        "Up to 4, with a double bed and two bunks."
      ],
      [
        "Is there a toilet inside?",
        "Yes, with a shower."
      ],
      [
        "Can we add a bonfire?",
        "Yes, add it now for ₹1,500."
      ],
      [
        "Can we stop anywhere?",
        "Yes, on the route you pick."
      ]
    ],
    "stops": [
      [
        "Enquiry",
        "Answered with routes and dates."
      ],
      [
        "Vehicle",
        "The next free vehicle is picked for you."
      ],
      [
        "Advance",
        "Paid in the chat, trip confirmed."
      ],
      [
        "On the road",
        "Crew updates and the live map."
      ],
      [
        "Return",
        "Distance checked, bill settled."
      ]
    ],
    "feats": [
      [
        "The free vehicle, picked",
        "Every new trip goes to the first free vehicle. No mix-ups."
      ],
      [
        "Papers and service dates",
        "Insurance, permits and service due dates tracked, with reminders."
      ],
      [
        "Your crew, on WhatsApp",
        "Trip jobs and guest problems reach the crew on duty."
      ],
      [
        "Live trip map",
        "See every vehicle on the road, with alerts if something is off."
      ]
    ]
  }
} satisfies Record<string, Solution>;

/* Heroicons (solid, MIT) path data for the solutions page labels. */
export const SOL_ICONS: Record<string, string[]> = {
  "HomeModernIcon": [
    "M19.006 3.705a.75.75 0 1 0-.512-1.41L6 6.838V3a.75.75 0 0 0-.75-.75h-1.5A.75.75 0 0 0 3 3v4.93l-1.006.365a.75.75 0 0 0 .512 1.41l16.5-6Z",
    "M3.019 11.114 18 5.667v3.421l4.006 1.457a.75.75 0 1 1-.512 1.41l-.494-.18v8.475h.75a.75.75 0 0 1 0 1.5H2.25a.75.75 0 0 1 0-1.5H3v-9.129l.019-.007ZM18 20.25v-9.566l1.5.546v9.02H18Zm-9-6a.75.75 0 0 0-.75.75v4.5c0 .414.336.75.75.75h3a.75.75 0 0 0 .75-.75V15a.75.75 0 0 0-.75-.75H9Z"
  ],
  "BuildingOffice2Icon": [
    "M3 2.25a.75.75 0 0 0 0 1.5v16.5h-.75a.75.75 0 0 0 0 1.5H15v-18a.75.75 0 0 0 0-1.5H3ZM6.75 19.5v-2.25a.75.75 0 0 1 .75-.75h3a.75.75 0 0 1 .75.75v2.25a.75.75 0 0 1-.75.75h-3a.75.75 0 0 1-.75-.75ZM6 6.75A.75.75 0 0 1 6.75 6h.75a.75.75 0 0 1 0 1.5h-.75A.75.75 0 0 1 6 6.75ZM6.75 9a.75.75 0 0 0 0 1.5h.75a.75.75 0 0 0 0-1.5h-.75ZM6 12.75a.75.75 0 0 1 .75-.75h.75a.75.75 0 0 1 0 1.5h-.75a.75.75 0 0 1-.75-.75ZM10.5 6a.75.75 0 0 0 0 1.5h.75a.75.75 0 0 0 0-1.5h-.75Zm-.75 3.75A.75.75 0 0 1 10.5 9h.75a.75.75 0 0 1 0 1.5h-.75a.75.75 0 0 1-.75-.75ZM10.5 12a.75.75 0 0 0 0 1.5h.75a.75.75 0 0 0 0-1.5h-.75ZM16.5 6.75v15h5.25a.75.75 0 0 0 0-1.5H21v-12a.75.75 0 0 0 0-1.5h-4.5Zm1.5 4.5a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75h-.008a.75.75 0 0 1-.75-.75v-.008Zm.75 2.25a.75.75 0 0 0-.75.75v.008c0 .414.336.75.75.75h.008a.75.75 0 0 0 .75-.75v-.008a.75.75 0 0 0-.75-.75h-.008ZM18 17.25a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75h-.008a.75.75 0 0 1-.75-.75v-.008Z"
  ],
  "MapPinIcon": [
    "m11.54 22.351.07.04.028.016a.76.76 0 0 0 .723 0l.028-.015.071-.041a16.975 16.975 0 0 0 1.144-.742 19.58 19.58 0 0 0 2.683-2.282c1.944-1.99 3.963-4.98 3.963-8.827a8.25 8.25 0 0 0-16.5 0c0 3.846 2.02 6.837 3.963 8.827a19.58 19.58 0 0 0 2.682 2.282 16.975 16.975 0 0 0 1.145.742ZM12 13.5a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
  ]
};
