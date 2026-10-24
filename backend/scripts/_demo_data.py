"""Made-up text for seed_local_demo.py. Every name, number and line here is invented: no real guest, business or chat."""

BRAND = "Wanderwheel Caravans"
SLUG = "demo-caravans"

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Vivaan", "Anika", "Arjun", "Sara", "Neel", "Tara", "Dev",
         "Zoya", "Kian", "Nisha", "Om", "Riya", "Yash", "Leela", "Aditya", "Pooja", "Ishaan", "Kavya", "Manav"]
LAST = ["Demo", "Testwala", "Sampleson", "Placeholder", "Mockrao", "Fakhri", "Dummyraj", "Trialkar"]
CITIES = ["Bengaluru", "Mumbai", "Pune", "Chennai", "Hyderabad", "Delhi", "Kochi", "Mysuru"]
OCCASIONS = [None, "honeymoon", "anniversary", "birthday", "family", "friends trip", None, "corporate offsite"]

DESTINATIONS = [
    {"key": "misty-hills", "name": "Misty Hills Loop", "km": 260, "hours": 6, "stops": ["Coffee Estate Camp", "Waterfall Point", "Base"]},
    {"key": "coastal-drive", "name": "Coastal Sunset Drive", "km": 380, "hours": 8, "stops": ["Lighthouse Beach", "Fishing Village", "Base"]},
]
PACKAGES = [
    {"key": "weekend-escape", "name": "Weekend Escape (2 nights)", "product": "multiday", "nights": 2, "amount": 38000, "dest": "misty-hills"},
    {"key": "sunset-overnight", "name": "Sunset Overnight", "product": "overnight", "nights": 1, "amount": 22000, "dest": "coastal-drive"},
]

# (direction, text). "in" = guest, "out" = staff.
CHATS = [
    [("in", "Hi! Saw your caravan on Instagram. Is it free this weekend for 4 people?"),
     ("out", "Hello! Thanks for writing to Wanderwheel. This weekend Wanderwheel 2 is free. Which route were you thinking of?"),
     ("in", "Misty Hills sounds lovely. Do you allow pets?"),
     ("out", "Yes, small pets are welcome with a cleaning fee. Shall I share the Weekend Escape details?")],
    [("in", "Hello, what is the price for 2 nights for a couple? It's our anniversary."),
     ("out", "Congratulations! Our team will call you shortly with the best package for your dates."),
     ("in", "Great, please call after 6pm.")],
    [("in", "Can we park the caravan near a beach overnight?"),
     ("out", "On the Coastal Sunset Drive we stop at a beach camp with permission. Would you like dates?")],
    [("in", "Is the driver included? We are 6 adults and 2 kids."),
     ("out", "Yes, a trained driver-host is always included. For 8 guests we suggest both caravans together."),
     ("in", "Hmm that may be over budget. Let me check with family."),
     ("out", "Sure, take your time. I can hold the dates till tomorrow evening.")],
    [("in", "Hi"), ("in", "Need caravan for 15th to 17th next month, Bangalore pickup")],
    [("in", "Do you do birthday decorations inside?"),
     ("out", "We can arrange fairy lights, a cake and balloons as an add-on."),
     ("in", "Perfect. Booking confirmed from my side, sending advance now."),
     ("out", "Received with thanks! Your booking is confirmed. See you soon.")],
    [("in", "How many km included in the overnight package?")],
    [("in", "We loved the trip last month! Want to book again for my parents."),
     ("out", "So happy to hear that! Which dates work for them?")],
]

TRANSCRIPTS = [
    [("guest", "Hi, I called about the caravan for next Saturday."),
     ("agent", "Sure! How many people will travel and from where?"),
     ("guest", "Four adults from Bengaluru, we want the hills route."),
     ("agent", "The Weekend Escape covers that. I will send the details on WhatsApp now."),
     ("guest", "Great, please do.")],
    [("guest", "What happens if it rains on the day?"),
     ("agent", "We can shift the date once for free if the forecast is bad."),
     ("guest", "Okay, that helps. We are comparing with a resort option."),
     ("agent", "Happy to answer anything. The caravan gives you sunrise views right from bed.")],
    [("guest", "I want to cancel my enquiry, plans changed."),
     ("agent", "No problem at all. Shall I keep you posted on offers?"),
     ("guest", "Yes, that is fine.")],
    [("agent", "Calling about your booking request for the coastal drive."),
     ("guest", "Yes! We are ready, how do I pay the advance?"),
     ("agent", "I will send a secure payment link on WhatsApp right after this call."),
     ("guest", "Perfect, thank you.")],
]

IG_CAPTIONS = [
    "Sunrise from the bed. Misty Hills Loop this weekend.", "Fairy lights, a cake and two very happy people.",
    "Our driver-hosts know every quiet camp spot.", "Coastal Sunset Drive: the golden hour never gets old.",
    "Pets welcome. Bruno approves.", "Inside Wanderwheel 2: the new lounge seats.", "Monsoon drives, cosy evenings.",
    "Family of six, two caravans, one big adventure.", "A coffee estate camp under the stars.",
    "Packing list for your first caravan trip.", "Behind the scenes: cleaning day.", "Thank you for 5,000 followers!",
]

PHOTO_CAPTIONS = [
    ("Misty Hills sunrise", (32, 94, 72), (214, 178, 120)), ("Coastal sunset", (224, 105, 74), (40, 60, 110)),
    ("Lounge interior", (120, 90, 60), (240, 225, 200)), ("Camp under stars", (10, 20, 50), (70, 60, 120)),
    ("Coffee estate stop", (60, 90, 40), (180, 200, 120)), ("Birthday setup", (200, 80, 140), (250, 210, 120)),
    ("Driver-host welcome", (30, 122, 90), (230, 240, 230)), ("Rainy window view", (70, 90, 110), (180, 200, 210)),
    ("Beach camp", (230, 190, 120), (40, 140, 170)), ("Family trip", (240, 160, 80), (90, 60, 140)),
    ("Bedroom with a view", (60, 60, 80), (220, 200, 170)), ("On the open road", (90, 90, 90), (200, 120, 60)),
]
