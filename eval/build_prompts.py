"""Builds eval/prompts.jsonl: 25 calibration + 40 held-out synthetic e-commerce support prompts.

All prompts are synthetic (written for this assignment). Indic prompts carry an English `note` gloss.
`hard` is a human annotation used ONLY for reporting (e.g. "quality on the hardest slice"); the router never sees it.
Run: python -m eval.build_prompts
"""
from __future__ import annotations

import json
from pathlib import Path

from .fixtures import SCHEMA_DOC, build_db

OUT = Path(__file__).resolve().parent / "prompts.jsonl"
P: list[dict] = []


def add(id, split, use_case, lang, hard, prompt, reference, context=None, target_lang=None, note=None):
    P.append({k: v for k, v in dict(id=id, split=split, use_case=use_case, lang=lang, hard=hard, prompt=prompt,
                                     context=context, target_lang=target_lang, reference=reference,
                                     note=note).items() if v is not None})


# ===================================================================== live_chat_reply (5 calib, 9 test)
# Judged against `must` facts (all taken from the context) and `must_not` (invented promises etc.).
add("L-c1", "calib", "live_chat_reply", "en", False,
    "Hi, is my earbuds order coming today? I need it before my trip tomorrow morning.",
    {"must": ["says it is expected today by 9 PM", "does not guarantee an exact time beyond the context"],
     "must_not": ["invents a delivery time other than today by 9 PM"]},
    context="Order #A1023 | status: Out for delivery | expected: today by 9 PM | payment: Prepaid (UPI) | items: boAt earbuds")
add("L-c2", "calib", "live_chat_reply", "hinglish", False,
    "Maine cooker order kiya tha, app mein delivered dikha raha hai par mujhe mila hi nahi. Ab kya karu?",
    {"must": ["replies in Hinglish", "acknowledges the item was not received despite 'delivered' status",
              "says a non-delivery complaint will be raised and investigated within 48 hours"],
     "must_not": ["promises an immediate refund"]},
    context="Order #B2210 | status: Delivered on 9 Nov | payment: COD | items: Prestige pressure cooker 3L | "
            "process for 'marked delivered but not received': raise non-delivery complaint, courier investigation within 48 hours",
    note="I ordered a cooker, app shows delivered but I never got it. What do I do now?")
add("L-c3", "calib", "live_chat_reply", "hi", False,
    "मेरा रिफंड अभी तक नहीं आया, कब तक आएगा?",
    {"must": ["replies in Hindi (Devanagari)", "mentions refund of ₹1,249", "initiated on 8 Nov",
              "5-7 business days to the original UPI account"],
     "must_not": ["invents a different amount or date"]},
    context="Order #C3301 | status: Refund initiated on 8 Nov to original UPI | refund amount ₹1,249 | refund SLA: 5-7 business days",
    note="My refund hasn't come yet, by when will it come?")
add("L-c4", "calib", "live_chat_reply", "ta", False,
    "என் புடவை ஆர்டர் எப்போது வரும்?",
    {"must": ["replies in Tamil script", "says expected delivery is 14 Nov", "says it is shipped / in transit"],
     "must_not": ["invents a different date"]},
    context="Order #D4410 | status: Shipped, in transit | expected delivery: 14 Nov | items: Cotton saree",
    note="When will my saree order arrive?")
add("L-c5", "calib", "live_chat_reply", "en", True,
    "I ordered the wrong size, can I cancel and how long till I get my money back? Also can you just change the size instead?",
    {"must": ["yes, free cancellation because it has not shipped", "refund to card in 5-7 business days",
              "size cannot be changed on a packed order; suggest cancel and re-order"],
     "must_not": ["says the size can be changed"]},
    context="Order #E5502 | status: Packed, not shipped | payment: Card | cancellation: free before shipping, "
            "refund to card in 5-7 business days | size change after packing: not supported")

add("L-t1", "test", "live_chat_reply", "en", False,
    "It's been 2 days past the delivery date. What is going on with my order?",
    {"must": ["apologises", "explains the delay is due to weather disruption at the Guwahati hub",
              "gives the new expected date 15 Nov"],
     "must_not": ["offers compensation, coupons or refunds not in the context"]},
    context="Order #F6011 | status: Delayed - weather disruption at Guwahati hub | new expected date: 15 Nov | payment: Prepaid")
add("L-t2", "test", "live_chat_reply", "en", False,
    "Shoes are a bit tight. Can I exchange for UK 10?",
    {"must": ["yes, size exchange is available", "within the 10-day window (until 20 Nov)", "explains it is done from the app"],
     "must_not": ["promises that UK 10 is in stock"]},
    context="Order #F6022 | status: Delivered 10 Nov | item: Nike running shoes UK 9 | return window: 10 days | "
            "size exchange: available via app, subject to stock")
add("L-t3", "test", "live_chat_reply", "en", True,
    "I was charged twice for the same order!! I want my money back right now or I'm reporting this.",
    {"must": ["calm and apologetic", "confirms only one order was created",
              "the duplicate ₹899 is auto-reversed within 48 hours"],
     "must_not": ["promises an instant refund right now", "says both payments will be kept"]},
    context="Order #F6033 | 2 payments of ₹899 captured on 11 Nov (UPI ref 5521, 5522) | one order created | "
            "duplicate payment policy: auto-reversal of the extra payment within 48 hours")
add("L-t4", "test", "live_chat_reply", "en", False,
    "where is my order? it said 10 mins, it's been 18",
    {"must": ["apologises for the delay", "says the rider is assigned and about 6 minutes away", "brief reply"],
     "must_not": ["invents a reason for the delay"]},
    context="Order #F6044 | quick-commerce | status: Rider assigned, 6 min away | items: milk, bread, eggs")
add("L-t5", "test", "live_chat_reply", "hinglish", False,
    "Aaj delivery aayegi kya? Mere paas sirf 2000 ka note hai, chalega?",
    {"must": ["replies in Hinglish", "yes, today by 8 PM", "amount due is ₹1,560 COD",
              "exact change is preferred; suggests paying by UPI on delivery instead"],
     "must_not": ["guarantees the rider will have change for ₹2000"]},
    context="Order #G7011 | status: Out for delivery | payment: COD ₹1,560 | expected: today by 8 PM | "
            "note: exact change preferred; UPI on delivery available",
    note="Will delivery come today? I only have a 2000 note, is that ok?")
add("L-t6", "test", "live_chat_reply", "hinglish", False,
    "Mera order cancel kyun ho gaya? Maine toh cancel nahi kiya tha. Paise kab wapas aayenge?",
    {"must": ["replies in Hinglish", "seller cancelled it because the item went out of stock",
              "refund of ₹2,349 initiated on 10 Nov to the original card", "5-7 business days"],
     "must_not": ["blames the customer", "invents a different amount"]},
    context="Order #G7022 | status: Cancelled by seller on 10 Nov (out of stock) | payment: Prepaid ₹2,349 | "
            "refund: initiated 10 Nov to original card, 5-7 business days",
    note="Why was my order cancelled? I didn't cancel it. When will I get my money back?")
add("L-t7", "test", "live_chat_reply", "hinglish", True,
    "Trimmer use kiya 2 baar, ab charge nahi ho raha. Return ho jayega? Box toh phek diya.",
    {"must": ["replies in Hinglish", "yes - a defective item is returnable even though it was used/opened",
              "the return window ends 13 Nov", "missing box does not block a defect return"],
     "must_not": ["refuses because the item was opened or used"]},
    context="Order #G7033 | status: Delivered 6 Nov | item: Philips trimmer ₹1,799 | return window: 7 days (ends 13 Nov) | "
            "category rule: personal care items returnable only if unopened OR defective; original box not required for defect returns",
    note="Used the trimmer twice, now it won't charge. Can it be returned? I threw away the box.")
add("L-t8", "test", "live_chat_reply", "hi", False,
    "मेरा रिटर्न पिकअप कब होगा?",
    {"must": ["replies in Hindi (Devanagari)", "pickup is on 13 Nov between 10 AM and 2 PM"],
     "must_not": ["invents a different date or time"]},
    context="Order #H8011 | status: Return pickup scheduled 13 Nov, 10 AM-2 PM | item: Kurta",
    note="When will my return pickup happen?")
add("L-t9", "test", "live_chat_reply", "ta", False,
    "நான் திருப்பி அனுப்பிய பொருளுக்கு பணம் இன்னும் வரவில்லை",
    {"must": ["replies in Tamil script", "₹699 was credited to the app wallet on 11 Nov", "asks them to check the wallet"],
     "must_not": ["says the refund is still pending"]},
    context="Order #H8022 | status: Delivered 9 Nov | refund for returned item: ₹699 credited to app wallet on 11 Nov",
    note="I still haven't received money for the item I sent back.")

# ===================================================================== ticket_intent (5 calib, 7 test)
for id, split, lang, hard, text, label, note in [
    ("T-c1", "calib", "en", False, "My order was supposed to come yesterday and the tracking hasn't updated since Monday.", "DELIVERY_STATUS", None),
    ("T-c2", "calib", "hinglish", False, "Paise kat gaye par order place nahi hua, UPI se pay kiya tha", "PAYMENT_ISSUE",
     "Money got deducted but the order wasn't placed, I paid via UPI"),
    ("T-c3", "calib", "en", False, "I received a blue shirt but I ordered black. Also the packet was torn.", "DAMAGED_OR_WRONG_ITEM", None),
    ("T-c4", "calib", "hi", False, "मुझे यह ऑर्डर कैंसल करना है, अभी तक शिप नहीं हुआ है", "CANCEL_ORDER",
     "I want to cancel this order, it hasn't shipped yet"),
    ("T-c5", "calib", "en", True, "I returned the jacket last week, pickup guy took it, but no money yet and now the app shows return cancelled?", "REFUND_STATUS", None),
    ("T-t1", "test", "en", False, "The size doesn't fit, I want to send it back and get a bigger one.", "RETURN_OR_EXCHANGE", None),
    ("T-t2", "test", "en", False, "Can I get a GST invoice for my last order? Need it for office reimbursement.", "OTHER", None),
    ("T-t3", "test", "en", True, "Order still not delivered after 10 days. At this point just cancel it and refund me.", "CANCEL_ORDER", None),
    ("T-t4", "test", "hinglish", False, "Bhai mixer toot ke aaya hai, jar mein crack hai", "DAMAGED_OR_WRONG_ITEM",
     "Bro the mixer arrived broken, there's a crack in the jar"),
    ("T-t5", "test", "hinglish", True, "Return pickup ho gaya 5 din pehle, refund ka koi update nahi, aur customer care call bhi nahi utha raha",
     "REFUND_STATUS", "Return was picked up 5 days ago, no refund update, and customer care isn't picking up calls"),
    ("T-t6", "test", "hi", False, "मेरा पार्सल कहाँ है? तीन दिन से कोई अपडेट नहीं", "DELIVERY_STATUS",
     "Where is my parcel? No update for three days"),
    ("T-t7", "test", "ta", False, "பணம் இரண்டு முறை கழிக்கப்பட்டது", "PAYMENT_ISSUE", "Money was deducted twice"),
]:
    add(id, split, "ticket_intent", lang, hard, text, {"label": label}, note=note)

# ===================================================================== policy_dispute (4 calib, 6 test)
POLICY = """Returns & refunds policy:
1. An item can be returned for a refund only if the return is requested within the order's return window (days counted from the delivery date to the return-request date).
2. Refund for a returned item = item price minus its share of any order-level coupon. The coupon is split across ALL items in the order in proportion to item price.
3. Items marked [non-returnable] get no refund unless covered by a valid damage claim.
4. A damage claim is valid only if raised within 48 hours of delivery. A valid claim refunds the item price minus its coupon share (even for non-returnable items) - or, if the customer asks for a replacement and the item is in stock, a replacement is issued instead and nothing is refunded.
5. The shipping fee is refunded only when valid damage claims cover every item in the order.
Decision labels: FULL_REFUND = customer gets back everything they paid for the order including shipping; PARTIAL_REFUND = some money but not all; NO_REFUND = no money and no replacement; REPLACEMENT = replacement issued, no money. If any money is refunded, use FULL_REFUND or PARTIAL_REFUND even if a replacement is also issued."""


def coupon_share(items: dict, coupon: float, name: str) -> float:
    return coupon * items[name] / sum(items.values())


def refund(items: dict, coupon: float, names: list[str]) -> float:
    return round(sum(items[n] - coupon_share(items, coupon, n) for n in names), 2)


POLICY_CASES = [
    # id, split, lang, order/request text, expected decision, expected amount (computed), note
    ("P-c1", "calib", "en",
     "Order: kurta ₹1,299, jeans ₹1,800, belt ₹401; coupon ₹350; shipping ₹0; return window 7 days; delivered 2 Nov. "
     "The customer requested a return of the kurta and the belt on 6 Nov (size issue). How much refund is due?",
     "PARTIAL_REFUND", refund({"kurta": 1299, "jeans": 1800, "belt": 401}, 350, ["kurta", "belt"]), None),
    ("P-c2", "calib", "en",
     "Order: smartwatch ₹2,499; no coupon; shipping ₹0; return window 10 days; delivered 1 Nov. "
     "The customer requested a return on 12 Nov because they changed their mind. What should happen?",
     "NO_REFUND", 0, None),
    ("P-c3", "calib", "hinglish",
     "Order: steel bottle ₹999, lunch box ₹1,499; no coupon; shipping ₹49; return window 7 days; delivered 4 Nov 9 AM. "
     "Customer ka message 5 Nov 8 AM: 'Bottle dented aayi hai, photo bhej raha hoon, paise wapas chahiye. Lunch box theek hai.' "
     "Kitna refund banta hai?",
     "PARTIAL_REFUND", refund({"bottle": 999, "box": 1499}, 0, ["bottle"]),
     "Customer's message: 'The bottle came dented, sending a photo, I want my money back. The lunch box is fine.' How much refund is due?"),
    ("P-c4", "calib", "en",
     "Order: air fryer ₹3,999 (only item); coupon ₹400; shipping ₹79; return window 7 days; delivered 6 Nov 10 AM. "
     "The customer reported on 7 Nov 6 AM that it arrived with a cracked basket, with photos, and wants their money back "
     "(not a replacement). What is due?",
     "FULL_REFUND", refund({"fryer": 3999}, 400, ["fryer"]) + 79, None),
    ("P-t1", "test", "en",
     "Order: t-shirt ₹800, shirt ₹1,200, jacket ₹2,000; coupon ₹400; shipping ₹0; return window 7 days; delivered 3 Nov. "
     "Return requested on 9 Nov for the t-shirt and the jacket (did not like the fit). How much is refunded?",
     "PARTIAL_REFUND", refund({"tshirt": 800, "shirt": 1200, "jacket": 2000}, 400, ["tshirt", "jacket"]), None),
    ("P-t2", "test", "en",
     "Order: kurta ₹1,350, lipstick ₹649 [non-returnable]; no coupon; shipping ₹0; return window 7 days; delivered 4 Nov. "
     "On 7 Nov the customer asked to return both: the kurta did not fit, and the lipstick shade (opened, not damaged) "
     "did not suit them. What is the refund?",
     "PARTIAL_REFUND", refund({"kurta": 1350, "lipstick": 649}, 0, ["kurta"]), None),
    ("P-t3", "test", "en",
     "Order: blender ₹1,899 (only item); no coupon; shipping ₹49; return window 10 days; delivered 2 Nov 10 AM. "
     "On 5 Nov 11 AM the customer reported the blender jar is cracked and asked for a refund, not a replacement. "
     "What is due?",
     "PARTIAL_REFUND", refund({"blender": 1899}, 0, ["blender"]), None),
    ("P-t4", "test", "hinglish",
     "Order: 3 items - kurti ₹500, dupatta ₹700, leggings ₹800; coupon ₹200; shipping ₹0; return window 7 days; delivered 5 Nov. "
     "Customer: 'Bhai dupatta ka colour photo se alag hai, 8 Nov ko return daal diya. Baaki dono rakh rahi hoon. Kitna paisa milega?'",
     "PARTIAL_REFUND", refund({"kurti": 500, "dupatta": 700, "leggings": 800}, 200, ["dupatta"]),
     "Customer: 'The dupatta colour is different from the photo, I raised a return on 8 Nov. Keeping the other two. How much will I get?'"),
    ("P-t5", "test", "hinglish",
     "Order: mixer grinder ₹3,200 (only item); no coupon; shipping ₹0; return window 7 days; delivered 10 Nov 11 AM; in stock: yes. "
     "Customer at 10 Nov 5 PM: 'Mixer ka jar toota hua aaya hai. Paise nahi chahiye, naya bhej do bas.' What should happen?",
     "REPLACEMENT", 0,
     "Customer: 'The mixer jar arrived broken. I don't want money, just send a new one.'"),
    ("P-t6", "test", "en",
     "Order: bedsheet ₹999, pillow covers ₹599; no coupon; shipping ₹0; return window 7 days; delivered 1 Nov. "
     "On 9 Nov the customer asked to return both and said the bedsheet had a tear when it arrived. What is the refund?",
     "NO_REFUND", 0, None),
]
for id, split, lang, text, decision, amount, note in POLICY_CASES:
    add(id, split, "policy_dispute", lang, True, POLICY + "\n\n" + text,
        {"decision": decision, "amount_inr": amount}, note=note)

# ===================================================================== chat_summary (3 calib, 5 test)
SUMMARIES = [
    ("S-c1", "calib", "hinglish", False,
     "Customer: Hi, mera order #K101 ka ek item missing hai, 2 T-shirts mangaye the, ek hi aaya.\n"
     "Agent: Sorry for this. Kya aap packet ki photo share kar sakte hain?\nCustomer: Haan bhej di.\n"
     "Agent: Thanks, maine missing item ki complaint raise kar di hai. 48 ghante mein resolution milega - ya toh dusra T-shirt bhejenge ya ₹499 refund.\n"
     "Customer: Theek hai, refund hi kar do.\nAgent: Noted, refund preference save kar di hai.",
     ["order #K101: 1 of 2 T-shirts missing", "customer shared a photo of the packet", "missing-item complaint raised",
      "resolution within 48 hours", "customer prefers a ₹499 refund over a replacement"],
     ["says the refund has already been paid"], "Missing item in a 2 T-shirt order; complaint raised; customer prefers refund."),
    ("S-c2", "calib", "en", False,
     "Customer: I need to change the delivery address for order #K202, I moved.\n"
     "Agent: The order is already shipped, so the address can't be changed now. I can ask the courier to hold it at the hub for pickup, or you can refuse delivery and we'll refund after it returns.\n"
     "Customer: How long would the refund take if I refuse?\nAgent: About 7-10 days after it reaches our warehouse.\n"
     "Customer: OK, hold it at the hub then. Which hub?\nAgent: Andheri East hub, you'll get an SMS with the pickup code.",
     ["address change not possible because #K202 already shipped", "options offered: hold at hub, or refuse for a refund in 7-10 days",
      "customer chose hub pickup at Andheri East", "pickup code will come by SMS"],
     ["says the address was changed"], None),
    ("S-c3", "calib", "hi", False,
     "ग्राहक: मेरा ऑर्डर #K303 देर से आ रहा है, कब तक आएगा?\nएजेंट: माफ़ कीजिए, बारिश की वजह से देरी है। नई तारीख 16 नवंबर है।\n"
     "ग्राहक: ठीक है, लेकिन अगर 16 तक नहीं आया तो मुझे कैंसल करना है।\nएजेंट: ज़रूर, 16 नवंबर के बाद आप ऐप से बिना शुल्क कैंसल कर सकते हैं।",
     ["order #K303 delayed due to rain", "new delivery date 16 Nov", "customer will cancel if not delivered by 16 Nov",
      "free cancellation from the app after 16 Nov"],
     ["says the order was cancelled"],
     "Customer: order K303 is late, when will it come? Agent: sorry, delay due to rain, new date 16 Nov. Customer: ok, but if not by 16th I want to cancel. Agent: sure, after 16 Nov you can cancel free from the app."),
    ("S-t1", "test", "hinglish", True,
     "Customer: Hello, mera order #M501 COD tha, delivery boy ne bola ₹1,850 dena hai par app pe ₹1,650 dikha raha tha.\n"
     "Agent: Sorry for the confusion. Check kiya - ₹200 ka coupon apply hua tha, delivery boy ke device pe update nahi hua.\n"
     "Customer: Toh maine delivery refuse kar di. Ab kya hoga?\n"
     "Agent: Order wapas warehouse jayega. Main naya order place kar deta hoon same coupon ke saath, ₹1,650 mein.\n"
     "Customer: Theek hai, par is baar UPI se pay karunga.\n"
     "Agent: Done, naya order #M502 prepaid hai, ₹1,650. Delivery 15 Nov tak. Aur pehle wale order pe koi charge nahi lagega.\nCustomer: Thik hai thanks.",
     ["COD order #M501: rider asked ₹1,850 but app showed ₹1,650", "cause: ₹200 coupon not updated on the rider's device",
      "customer refused delivery of #M501", "new prepaid (UPI) order #M502 placed at ₹1,650 with the coupon",
      "delivery by 15 Nov", "no charge for the original order"],
     ["says the customer paid ₹1,850"],
     "COD price mismatch (coupon not synced to rider device); customer refused; agent placed new prepaid order M502 at ₹1,650, delivery by 15 Nov; no charge on old order."),
    ("S-t2", "test", "hinglish", False,
     "Customer: Bhai mera mixer grinder #M601 toota hua aaya.\nAgent: Bahut sorry. Unboxing video hai?\n"
     "Customer: Video nahi hai, photos hain.\nAgent: Photos chalengi. Replacement 3-5 din mein aayega, aur purana pickup usi time hoga.\n"
     "Customer: Pickup ke time mujhe ghar pe rehna padega?\nAgent: Haan, ya kisi ko bata dijiye jo product handover kar sake.",
     ["mixer grinder #M601 arrived broken", "photos accepted (no unboxing video)", "replacement in 3-5 days",
      "old unit picked up at the same time", "someone must be home to hand it over"],
     ["says a refund will be issued"],
     "Mixer arrived broken; photos accepted instead of video; replacement in 3-5 days with pickup of old unit at the same time; someone must be home."),
    ("S-t3", "test", "en", False,
     "Customer: My refund for order #M701 shows completed but I don't see it in my bank.\n"
     "Agent: The refund of ₹2,199 was processed on 7 Nov with bank reference RRN 8812. Banks can take up to 3 business days to show it.\n"
     "Customer: It's been 4 business days.\n"
     "Agent: Understood. I'm raising a ticket with our payments team; they'll share a bank confirmation letter within 48 hours that you can take to your bank.\nCustomer: Fine.",
     ["refund ₹2,199 for #M701 processed 7 Nov, RRN 8812", "not visible in bank after 4 business days",
      "ticket raised with payments team", "bank confirmation letter within 48 hours"],
     ["says the money will be refunded again"], None),
    ("S-t4", "test", "hi", False,
     "ग्राहक: मैंने गलत साइज़ ऑर्डर कर दिया, #M801, क्या बदल सकते हैं?\n"
     "एजेंट: हाँ, डिलीवरी के 10 दिन के अंदर साइज़ एक्सचेंज मुफ्त है। आपको कौन सा साइज़ चाहिए?\n"
     "ग्राहक: L चाहिए, अभी M आया है।\nएजेंट: L स्टॉक में है। एक्सचेंज बुक कर दिया है, पिकअप और नई डिलीवरी 14 नवंबर को एक साथ होगी।",
     ["wrong size on #M801: received M, wants L", "free size exchange within 10 days of delivery", "L is in stock",
      "exchange booked; pickup and new delivery together on 14 Nov"],
     ["says a refund was issued"],
     "Customer: ordered wrong size, #M801, can it be changed? Agent: yes, free size exchange within 10 days of delivery, which size? Customer: need L, got M. Agent: L in stock, exchange booked, pickup and new delivery together on 14 Nov."),
    ("S-t5", "test", "ta", False,
     "Customer: என் ஆர்டர் #M901 cancel பண்ணணும்.\n"
     "Agent: ஆர்டர் இன்னும் ship ஆகவில்லை, அதனால் free-ஆ cancel பண்ணலாம். Refund 5-7 நாட்களில் உங்கள் card-க்கு வரும்.\n"
     "Customer: சரி, cancel பண்ணுங்க.\nAgent: Cancel ஆகிவிட்டது. Confirmation SMS வரும்.",
     ["#M901 cancelled before shipping, free of charge", "refund to card in 5-7 days", "confirmation SMS will be sent"],
     ["says the order was shipped"],
     "Customer: I need to cancel order M901. Agent: not shipped yet so free cancel; refund to your card in 5-7 days. Customer: ok, cancel. Agent: cancelled, confirmation SMS will come."),
]
for id, split, lang, hard, transcript, facts, must_not, note in SUMMARIES:
    add(id, split, "chat_summary", lang, hard, transcript, {"must": facts, "must_not": must_not}, note=note)

# ===================================================================== attr_extract (3 calib, 5 test)
ATTR_HDR = ("Attributes: brand, color, size, material, pack_count (number of units in the pack), "
            "price_inr (current selling price as a number: not MRP, and before any coupon codes or bank offers)\nListing: ")
for id, split, lang, hard, listing, ref, note in [
    ("A-c1", "calib", "en", False, "Puma Men's Running Shoes - Black/White, UK 9, mesh upper, lightweight. MRP ₹4,999, now ₹2,499.",
     {"brand": "Puma", "color": "black/white", "size": "UK 9", "material": "mesh", "pack_count": None, "price_inr": 2499}, None),
    ("A-c2", "calib", "en", False, "Tata Sampann Unpolished Toor Dal, 1 kg x 2 (pack of 2), ₹378",
     {"brand": "Tata Sampann", "color": None, "size": "1 kg", "material": None, "pack_count": 2, "price_inr": 378}, None),
    ("A-c3", "calib", "hinglish", False, "Bhai mast cotton kurta hai, FabIndia ka, maroon colour, size XL, sirf ₹1,299 mein, 1 piece",
     {"brand": "FabIndia", "color": "maroon", "size": "XL", "material": "cotton", "pack_count": 1, "price_inr": 1299},
     "Great cotton kurta, by FabIndia, maroon colour, size XL, only ₹1,299, 1 piece"),
    ("A-t1", "test", "en", False, "boAt Rockerz 450 Bluetooth headphones, Luscious Black, on-ear, 15hr battery. Deal price: ₹1,499 (MRP ₹3,990).",
     {"brand": "boAt", "color": "black", "size": None, "material": None, "pack_count": None, "price_inr": 1499}, None),
    ("A-t2", "test", "en", False, "Milton Thermosteel Flip Lid Flask 1000 ml, silver, stainless steel, set of 2 - ₹1,199",
     {"brand": "Milton", "color": "silver", "size": "1000 ml", "material": "stainless steel", "pack_count": 2, "price_inr": 1199}, None),
    ("A-t3", "test", "en", True, "Pack of 3 Jockey men's cotton-modal briefs, assorted colours (navy, grey, black), size M. ₹899 for the pack, ₹300 each if bought singly.",
     {"brand": "Jockey", "color": "navy/grey/black", "size": "M", "material": "cotton modal", "pack_count": 3, "price_inr": 899}, None),
    ("A-t4", "test", "hinglish", False, "Prestige ka 5 litre pressure cooker, aluminium body, silver color, offer price ₹1,645",
     {"brand": "Prestige", "color": "silver", "size": "5 litre", "material": "aluminium", "pack_count": None, "price_inr": 1645},
     "Prestige 5 litre pressure cooker, aluminium body, silver colour, offer price ₹1,645"),
    ("A-t5", "test", "en", False, "Lakmé 9to5 Primer + Matte Lipstick, shade Maroon Mate, 3.6 g, ₹595",
     {"brand": "Lakme", "color": "maroon", "size": "3.6 g", "material": None, "pack_count": None, "price_inr": 595}, None),
]:
    add(id, split, "attr_extract", lang, hard, ATTR_HDR + listing, {"fields": ref}, note=note)

# ===================================================================== catalogue_translate (3 calib, 4 test)
for id, split, tl, hard, src, keep in [
    ("C-c1", "calib", "hi", False, "Women's cotton straight kurta with pockets, navy blue, size M. Machine wash cold.", ["M"]),
    ("C-c2", "calib", "ta", False, "Stainless steel water bottle, 1 litre, leak-proof lid, keeps drinks cold for 24 hours.", ["1", "24"]),
    ("C-c3", "calib", "hi", False, "Prestige Iris 750W mixer grinder with 3 jars, 2-year warranty.", ["Prestige", "Iris", "750", "3", "2"]),
    ("C-t1", "test", "hi", False, "Men's slim-fit denim jeans, stretchable, dark blue, waist 32. Do not bleach.", ["32"]),
    ("C-t2", "test", "ta", False, "Pure silk Kanjivaram saree with zari border, 6.3 metres including blouse piece. Dry clean only.", ["6.3"]),
    ("C-t3", "test", "hi", True, "Philips BT1232 cordless beard trimmer, 18 length settings (0.5-10 mm), 30 minutes run time on an 8-hour charge, USB charging.",
     ["Philips", "BT1232", "18", "0.5", "10", "30", "8", "USB"]),
    ("C-t4", "test", "ta", True, "Aashirvaad Shudh Chakki Atta, 10 kg. 100% whole wheat, 0% maida. Best before 3 months from packaging.",
     ["Aashirvaad", "10", "100", "0", "3"]),
]:
    add(id, split, "catalogue_translate", tl, hard, src, {"keep": keep}, target_lang=tl)

# ===================================================================== code (2 calib, 4 test), scored by execution
SQL = [
    ("Q-c1", "calib", "Total GMV (sum of amount_inr) of DELIVERED orders per payment_mode for orders created in October 2026. "
     "Return columns payment_mode, gmv (rounded to 2 decimals), highest GMV first.",
     "SELECT payment_mode, ROUND(SUM(amount_inr),2) AS gmv FROM orders WHERE status='DELIVERED' "
     "AND created_at >= '2026-10-01' AND created_at < '2026-11-01' GROUP BY payment_mode ORDER BY gmv DESC"),
    ("Q-c2", "calib", "Number of returns per reason for orders created in September 2026. Return columns reason, returns.",
     "SELECT r.reason, COUNT(*) AS returns FROM returns r JOIN orders o ON o.order_id=r.order_id "
     "WHERE o.created_at >= '2026-09-01' AND o.created_at < '2026-10-01' GROUP BY r.reason"),
    ("Q-t1", "test", "Top 10 pincodes by RTO rate for orders created in October 2026, among pincodes with at least 50 orders "
     "that month. RTO rate = RTO orders / all orders. Return columns pincode, rto_rate (rounded to 3 decimals), highest first.",
     "SELECT pincode, ROUND(1.0*SUM(status='RTO')/COUNT(*),3) AS rto_rate FROM orders WHERE created_at >= '2026-10-01' "
     "AND created_at < '2026-11-01' GROUP BY pincode HAVING COUNT(*) >= 50 ORDER BY rto_rate DESC LIMIT 10"),
    ("Q-t2", "test", "Customers who placed at least 3 COD orders created in October 2026 and had at least one of those October COD "
     "orders end in RTO. Return column customer_id, ascending.",
     "SELECT customer_id FROM orders WHERE payment_mode='COD' AND created_at >= '2026-10-01' AND created_at < '2026-11-01' "
     "GROUP BY customer_id HAVING COUNT(*) >= 3 AND SUM(status='RTO') >= 1 ORDER BY customer_id"),
    ("Q-t3", "test", "Return rate by city for DELIVERED orders created in September 2026: share of those orders that have at least "
     "one row in returns. Return columns city, return_rate (rounded to 3 decimals), highest first.",
     "SELECT o.city, ROUND(1.0*COUNT(DISTINCT r.order_id)/COUNT(DISTINCT o.order_id),3) AS return_rate FROM orders o "
     "LEFT JOIN returns r ON r.order_id=o.order_id WHERE o.status='DELIVERED' AND o.created_at >= '2026-09-01' "
     "AND o.created_at < '2026-10-01' GROUP BY o.city ORDER BY return_rate DESC"),
    ("Q-t4", "test", "Average number of days between order creation and return creation, per return reason, across all returns. "
     "Return columns reason, avg_days (rounded to 1 decimal).",
     "SELECT r.reason, ROUND(AVG(julianday(r.created_at)-julianday(o.created_at)),1) AS avg_days FROM returns r "
     "JOIN orders o ON o.order_id=r.order_id GROUP BY r.reason"),
]
for id, split, ask, ref_sql in SQL:
    add(id, split, "code", "en", True, SCHEMA_DOC + "\n\nRequest: " + ask, {"sql": ref_sql})


# ===================================================================== HARD additions
# Added after calibration showed the cheap model passing 24/25 of the first set (our first "hard" items were not
# hard for it). Added to BOTH splits before any held-out result was looked at.
HARD_POLICY = [
    ("HP-c1", "calib", "en",
     "Order: running shoes ₹2,400, socks pack ₹300 [non-returnable], cap ₹600, backpack ₹2,700; coupon ₹900; shipping ₹99; "
     "return window 7 days; delivered 3 Nov 6 PM. Events: (a) 4 Nov 2 PM - customer reports the shoes arrived with a torn sole, "
     "with photos, and wants a refund (not a replacement). (b) 9 Nov - customer requests a return of the socks (unopened, "
     "changed mind) and the cap (did not like it). (c) 12 Nov - customer also asks to return the backpack. "
     "What is the total refund?",
     "PARTIAL_REFUND", refund({"shoes": 2400, "socks": 300, "cap": 600, "bag": 2700}, 900, ["shoes", "cap"]), None),
    ("HP-c2", "calib", "hinglish",
     "Order: pressure cooker ₹2,000, gasket set ₹200 [non-returnable]; coupon ₹220; shipping ₹50; return window 7 days; "
     "delivered 6 Nov 10 AM. Customer ka message 7 Nov 9 AM: 'Cooker ka lid crack hai aur gasket bhi fata hua aaya hai, "
     "photos bhej di hain. Dono ka paisa wapas chahiye, replacement nahi.' Total kitna refund banta hai?",
     "FULL_REFUND", refund({"cooker": 2000, "gasket": 200}, 220, ["cooker", "gasket"]) + 50,
     "Customer (7 Nov 9 AM): 'The cooker lid is cracked and the gasket also arrived torn, sent photos. I want money back for both, not a replacement.' How much refund is due in total?"),
    ("HP-t1", "test", "en",
     "Order: phone case ₹500, screen guard ₹300 [non-returnable], charger ₹1,200, earphones ₹2,000; coupon ₹600; shipping ₹49; "
     "return window 10 days; delivered 1 Nov 11 AM. Events: (a) 3 Nov 12 PM - customer reports the charger is not working and "
     "asks for a refund. (b) 5 Nov - customer returns the screen guard (opened, works fine, wrong model). (c) 10 Nov - customer "
     "returns the earphones (did not like the sound). The phone case is kept. What is the total refund?",
     "PARTIAL_REFUND", refund({"case": 500, "guard": 300, "charger": 1200, "earphones": 2000}, 600, ["charger", "earphones"]), None),
    ("HP-t2", "test", "en",
     "Order: mattress ₹12,000, 2 pillows ₹1,000 (one line item), bedsheet ₹1,000; coupon ₹1,400; shipping ₹0; return window 7 days; "
     "delivered 2 Nov 4 PM; mattress in stock: yes. Events: (a) 3 Nov 10 AM - customer reports the mattress arrived with a "
     "water stain, with photos, and asks for a replacement. (b) 8 Nov - customer returns the bedsheet (colour mismatch). "
     "Pillows kept. What is the outcome and the refund amount?",
     "PARTIAL_REFUND", refund({"mattress": 12000, "pillows": 1000, "bedsheet": 1000}, 1400, ["bedsheet"]), None),
    ("HP-t3", "test", "hinglish",
     "Order: silk saree ₹3,000, blouse piece ₹500, fall-pico stitching service ₹200 [non-returnable]; coupon ₹370; shipping ₹60; "
     "return window 7 days; delivered 4 Nov 1 PM. Customer ka message 5 Nov 11 AM: 'Saree ek jagah se phati hui hai (photo "
     "bheji hai) aur blouse piece ka colour galat aaya hai, dono return karne hain aur paisa wapas chahiye. Fall-pico ka bhi "
     "refund karo, saree hi nahi rakhni.' Total refund kitna hoga?",
     "PARTIAL_REFUND", refund({"saree": 3000, "blouse": 500, "fallpico": 200}, 370, ["saree", "blouse"]),
     "Customer (5 Nov 11 AM): 'The saree is torn in one place (sent photo) and the blouse piece is the wrong colour, I want to return both and get my money back. Refund the fall-pico too, I don't want to keep the saree.' What is the total refund?"),
]
for id, split, lang, text, decision, amount, note in HARD_POLICY:
    add(id, split, "policy_dispute", lang, True, POLICY + "\n\n" + text,
        {"decision": decision, "amount_inr": amount}, note=note)

HARD_SQL = [
    ("HQ-c1", "calib", "For each city, find the pincode with the highest total amount_inr of orders created in October 2026 "
     "(all statuses) and that pincode's share of the city's October total. Return columns city, pincode, share "
     "(rounded to 3 decimals).",
     "WITH t AS (SELECT city, pincode, SUM(amount_inr) gmv FROM orders WHERE created_at >= '2026-10-01' AND created_at < '2026-11-01' "
     "GROUP BY city, pincode), r AS (SELECT city, pincode, gmv, RANK() OVER (PARTITION BY city ORDER BY gmv DESC) rk, "
     "SUM(gmv) OVER (PARTITION BY city) city_gmv FROM t) SELECT city, pincode, ROUND(gmv/city_gmv,3) AS share FROM r WHERE rk=1"),
    ("HQ-t1", "test", "For each city, the percentage change in the number of DELIVERED orders from September 2026 to October 2026 "
     "(by created_at month), i.e. 100*(oct-sep)/sep. Return columns city, pct_change (rounded to 1 decimal), highest first.",
     "SELECT city, ROUND(100.0*(SUM(created_at >= '2026-10-01' AND created_at < '2026-11-01') - SUM(created_at >= '2026-09-01' "
     "AND created_at < '2026-10-01'))/SUM(created_at >= '2026-09-01' AND created_at < '2026-10-01'),1) AS pct_change "
     "FROM orders WHERE status='DELIVERED' GROUP BY city ORDER BY pct_change DESC"),
    ("HQ-t2", "test", "For each customer who has at least one RTO order, take their FIRST RTO order (earliest created_at) and the "
     "next order that customer created after it (any status). Ignore customers with no later order. Group by the payment_mode "
     "of that first RTO order and return columns payment_mode, avg_gap_days (average days between the two created_at "
     "timestamps, rounded to 1 decimal).",
     "WITH fr AS (SELECT customer_id, MIN(created_at) AS rto_at FROM orders WHERE status='RTO' GROUP BY customer_id), "
     "fx AS (SELECT fr.customer_id, fr.rto_at, o.payment_mode, (SELECT MIN(o2.created_at) FROM orders o2 WHERE "
     "o2.customer_id=fr.customer_id AND o2.created_at > fr.rto_at) AS next_at FROM fr JOIN orders o ON "
     "o.customer_id=fr.customer_id AND o.created_at=fr.rto_at AND o.status='RTO') SELECT payment_mode, "
     "ROUND(AVG(julianday(next_at)-julianday(rto_at)),1) AS avg_gap_days FROM fx WHERE next_at IS NOT NULL GROUP BY payment_mode"),
]
for id, split, ask, ref_sql in HARD_SQL:
    add(id, split, "code", "en", True, SCHEMA_DOC + "\n\nRequest: " + ask, {"sql": ref_sql})

HARD_SUMMARIES = [
    ("HS-c1", "calib", "hinglish",
     "Customer: Hi, order #N501 ka kurta size chhota hai, exchange karna hai.\n"
     "Agent: Sure, exchange ke liye L size check karta hoon... sorry, L out of stock hai.\n"
     "Customer: Accha toh phir refund kar do.\nAgent: Theek hai, refund 3-5 din mein aa jayega.\n"
     "Customer: Order COD tha, paise kahan aayenge?\n"
     "Agent: Ek minute... correction: COD orders ka refund bank transfer (NEFT) se hota hai, usme 7-10 working days lagte hain, 3-5 nahi. "
     "Aapko app mein 15 Nov tak bank details add karni hongi.\nCustomer: Ok. Pickup kab hoga?\n"
     "Agent: Pickup 13 Nov ko hai. Refund amount ₹1,499 hoga.",
     ["order #N501 kurta too small; exchange not possible because L is out of stock", "customer chose a refund of ₹1,499",
      "COD so refund by bank transfer (NEFT) in 7-10 working days (agent corrected the earlier 3-5 days)",
      "customer must add bank details in the app by 15 Nov", "pickup on 13 Nov"],
     ["says the refund takes 3-5 days", "says an exchange was booked"],
     "Kurta too small, wants exchange; L out of stock so customer asks refund; agent says 3-5 days, then corrects: COD refunds go by bank transfer (NEFT) in 7-10 working days, add bank details in app by 15 Nov; pickup 13 Nov; refund ₹1,499."),
    ("HS-t1", "test", "hinglish",
     "Customer: Do problem hain. Pehla, order #N11 abhi tak nahi aaya, 3 din late hai.\n"
     "Agent: Sorry, #N11 ki nayi delivery date 16 Nov hai. Delay ke liye maine aapke account mein ₹50 ka coupon daal diya hai.\n"
     "Customer: Aur #N12 mein galat item aaya hai, maine blue bottle mangayi thi, green aayi.\n"
     "Agent: #N12 ke liye pickup 14 Nov ko schedule kar diya hai. Pickup ke baad quality check hoga, phir replacement bhejenge.\n"
     "Customer: Aur mera phone number bhi change kar do, naya number 98xxxxxx12 hai.\n"
     "Agent: Phone number chat se change nahi ho sakta, aapko app ke Settings > Profile mein OTP se karna hoga.\nCustomer: Ok theek hai.",
     ["#N11 is 3 days late; new delivery date 16 Nov; ₹50 coupon added for the delay",
      "#N12 wrong item (green instead of blue bottle); pickup 14 Nov; replacement sent after the pickup quality check",
      "phone number NOT changed in chat; customer must change it in app Settings > Profile with OTP"],
     ["says the phone number was changed", "mixes up which order got the coupon and which gets the replacement"],
     "Two issues: N11 late, new date 16 Nov, ₹50 coupon for delay; N12 wrong item (green not blue), pickup 14 Nov, replacement after QC. Phone number can't be changed in chat - do it in app settings with OTP."),
    ("HS-t2", "test", "en",
     "Customer: Order #N21 had a lamp and a rug. The lamp arrived broken.\n"
     "Agent: So sorry! You'll get a full refund including the shipping charge.\n"
     "Supervisor (joining): Correction to the above - since only the lamp was damaged and the rug is fine, shipping (₹79) is not refundable. "
     "The refund is ₹1,120 for the lamp, to your original UPI in 5-7 days.\n"
     "Customer: That's not what I was told. I'm not happy, I want this escalated.\n"
     "Supervisor: Understood, I've created escalation ticket ESC-4471; the escalations team will call you within 24 hours.\n"
     "Customer: Fine, but I'm accepting the ₹1,120 for now.",
     ["only the lamp was damaged; rug is fine", "refund ₹1,120 for the lamp to original UPI in 5-7 days",
      "shipping ₹79 NOT refunded (supervisor corrected the agent's full-refund statement)",
      "customer unhappy; escalation ticket ESC-4471, call within 24 hours", "customer accepted ₹1,120 for now"],
     ["says shipping is refunded", "says a full refund was given"], None),
]
for id, split, lang, transcript, facts, must_not, note in HARD_SUMMARIES:
    add(id, split, "chat_summary", lang, True, transcript, {"must": facts, "must_not": must_not}, note=note)

for id, split, lang, listing, ref in [
    ("HA-c1", "calib", "en", "Combo offer!! Bajaj 1000W dry iron (white & blue) + FREE ironing board cover. Was ₹1,599, deal ₹899, "
     "extra ₹100 off with code IRON100 (₹799 effective). Box contains 1 iron.",
     {"brand": "Bajaj", "color": "white/blue", "size": None, "material": None, "pack_count": 1, "price_inr": 899}),
    ("HA-t1", "test", "en", "Set of 6 Cello glass tumblers, 300 ml each (1.8 L total), transparent. MRP 1,200 | Sale 649 | "
     "Bank offer: 10% instant discount on HDFC cards.",
     {"brand": "Cello", "color": "transparent", "size": "300 ml", "material": "glass", "pack_count": 6, "price_inr": 649}),
]:
    add(id, split, "attr_extract", lang, True, ATTR_HDR + listing, {"fields": ref})


# Extra SQL calibration prompts: added because the first benchmark showed a decision resting on a 3-sample
# calibration cell. Calibration split only; held-out prompts unchanged.
SQL_MORE = [
    ("Q-c3", "Number of orders by status for orders created in November 2026. Return columns status, orders.",
     "SELECT status, COUNT(*) AS orders FROM orders WHERE created_at >= '2026-11-01' AND created_at < '2026-12-01' GROUP BY status"),
    ("Q-c4", "Average order value (amount_inr) by city for UPI orders across all months. Return columns city, avg_value "
     "(rounded to 2 decimals) for the top 3 cities by average value.",
     "SELECT city, ROUND(AVG(amount_inr),2) AS avg_value FROM orders WHERE payment_mode='UPI' GROUP BY city ORDER BY avg_value DESC LIMIT 3"),
    ("Q-c5", "For COD orders created in September 2026, the share that ended in RTO, per city. Return columns city, "
     "rto_share (rounded to 3 decimals).",
     "SELECT city, ROUND(1.0*SUM(status='RTO')/COUNT(*),3) AS rto_share FROM orders WHERE payment_mode='COD' "
     "AND created_at >= '2026-09-01' AND created_at < '2026-10-01' GROUP BY city"),
    ("Q-c6", "For each return reason, the total refund_inr and the number of distinct customers who made such a return. "
     "Return columns reason, total_refund (rounded to 2 decimals), customers.",
     "SELECT r.reason, ROUND(SUM(r.refund_inr),2) AS total_refund, COUNT(DISTINCT o.customer_id) AS customers FROM returns r "
     "JOIN orders o ON o.order_id=r.order_id GROUP BY r.reason"),
    ("Q-c7", "For each customer with at least two orders, the number of days between their first and second order "
     "(by created_at). Return a single column avg_days: the average of that gap across customers, rounded to 2 decimals.",
     "WITH r AS (SELECT customer_id, created_at, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at) rn FROM orders) "
     "SELECT ROUND(AVG(julianday(b.created_at)-julianday(a.created_at)),2) AS avg_days FROM r a JOIN r b "
     "ON a.customer_id=b.customer_id AND a.rn=1 AND b.rn=2"),
    ("Q-c8", "For each city, the top 3 customers by total amount_inr of orders created in October 2026 (all statuses). "
     "Return columns city, customer_id, spend (rounded to 2 decimals).",
     "WITH s AS (SELECT city, customer_id, SUM(amount_inr) spend FROM orders WHERE created_at >= '2026-10-01' "
     "AND created_at < '2026-11-01' GROUP BY city, customer_id), r AS (SELECT city, customer_id, spend, "
     "ROW_NUMBER() OVER (PARTITION BY city ORDER BY spend DESC) rn FROM s) SELECT city, customer_id, ROUND(spend,2) AS spend "
     "FROM r WHERE rn <= 3"),
]
for id, ask, ref_sql in SQL_MORE:
    add(id, "calib", "code", "en", id in ("Q-c7", "Q-c8"), SCHEMA_DOC + "\n\nRequest: " + ask, {"sql": ref_sql})


def main() -> None:
    # Sanity: reference SQL runs and returns rows; split sizes and language mix.
    con = build_db()
    for p in P:
        if p["use_case"] == "code":
            rows = con.execute(p["reference"]["sql"]).fetchall()
            assert rows, f"{p['id']} reference SQL returned no rows"
    ids = [p["id"] for p in P]
    assert len(ids) == len(set(ids)), "duplicate ids"
    OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in P) + "\n")
    from collections import Counter
    for split in ("calib", "test"):
        rows = [p for p in P if p["split"] == split]
        print(f"{split}: {len(rows)} prompts | use cases {dict(Counter(p['use_case'] for p in rows))}")
        print(f"   langs {dict(Counter(p['lang'] for p in rows))} | hard {sum(p['hard'] for p in rows)}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
