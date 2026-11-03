"""Tools a website can reveal in its HTML (script/iframe/link addresses). Edit freely.

kind: booking · chat · whatsapp_tool · crm_form · analytics · ads_pixel · payments · builder
competitor=True: a tool that already does part of what TechDeva sells (the lead is weaker or needs a switch story).
"""
from __future__ import annotations

SIGNATURES: dict[str, tuple[str, str, bool]] = {
    # booking / scheduling
    "fresha.com": ("Fresha", "booking", True), "booksy.com": ("Booksy", "booking", True),
    "vagaro.com": ("Vagaro", "booking", True), "zenoti.com": ("Zenoti", "booking", True),
    "mindbodyonline.com": ("Mindbody", "booking", True), "setmore.com": ("Setmore", "booking", True),
    "simplybook.me": ("SimplyBook", "booking", True), "phorest.com": ("Phorest", "booking", True),
    "gettimely.com": ("Timely", "booking", True), "joinblvd.com": ("Boulevard", "booking", True),
    "calendly.com": ("Calendly", "booking", False), "acuityscheduling.com": ("Acuity", "booking", True),
    "squareup.com/appointments": ("Square Appointments", "booking", True), "glamera": ("Glamera", "booking", True),
    "okadoc.com": ("Okadoc", "booking", True), "practo.com": ("Practo", "booking", True),
    "clinicea.com": ("Clinicea", "booking", True), "vezeeta.com": ("Vezeeta", "booking", True),
    "doctoruna.com": ("Doctoruna", "booking", True), "opentable.com": ("OpenTable", "booking", True),
    "sevenrooms.com": ("SevenRooms", "booking", True), "zohobookings": ("Zoho Bookings", "booking", True),
    # chat widgets / WhatsApp automation
    "wati.io": ("WATI", "whatsapp_tool", True), "interakt.shop": ("Interakt", "whatsapp_tool", True),
    "gallabox.com": ("Gallabox", "whatsapp_tool", True), "zoko.io": ("Zoko", "whatsapp_tool", True),
    "respond.io": ("respond.io", "whatsapp_tool", True), "trengo.com": ("Trengo", "whatsapp_tool", True),
    "manychat.com": ("ManyChat", "whatsapp_tool", True), "elfsight.com": ("Elfsight widget", "chat", False),
    "getbutton.io": ("GetButton chat", "chat", False), "tawk.to": ("tawk.to", "chat", True),
    "intercom.io": ("Intercom", "chat", True), "crisp.chat": ("Crisp", "chat", True),
    "tidio.co": ("Tidio", "chat", True), "livechatinc.com": ("LiveChat", "chat", True),
    "freshchat": ("Freshchat", "chat", True), "zopim": ("Zendesk Chat", "chat", True),
    # CRM / forms
    "hubspot": ("HubSpot", "crm_form", True), "zoho.com/crm": ("Zoho CRM", "crm_form", True),
    "salesforce": ("Salesforce", "crm_form", True), "pipedrive": ("Pipedrive", "crm_form", True),
    "typeform.com": ("Typeform", "crm_form", False), "jotform": ("Jotform", "crm_form", False),
    "docs.google.com/forms": ("Google Forms", "crm_form", False), "formspree.io": ("Formspree", "crm_form", False),
    "wpforms": ("WPForms", "crm_form", False), "contact-form-7": ("Contact Form 7", "crm_form", False),
    "mailchimp": ("Mailchimp", "crm_form", False), "klaviyo": ("Klaviyo", "crm_form", False),
    # tracking
    "googletagmanager.com": ("Google Tag Manager", "analytics", False),
    "google-analytics.com": ("Google Analytics", "analytics", False), "gtag(": ("Google Analytics", "analytics", False),
    "hotjar": ("Hotjar", "analytics", False), "clarity.ms": ("Microsoft Clarity", "analytics", False),
    "connect.facebook.net": ("Meta Pixel", "ads_pixel", False), "snap.licdn.com": ("LinkedIn Insight", "ads_pixel", False),
    "analytics.tiktok.com": ("TikTok Pixel", "ads_pixel", False), "sc-static.net": ("Snap Pixel", "ads_pixel", False),
    # payments
    "stripe.com": ("Stripe", "payments", False), "checkout.com": ("Checkout.com", "payments", False),
    "tabby.ai": ("Tabby", "payments", False), "tamara.co": ("Tamara", "payments", False),
    "paytabs": ("PayTabs", "payments", False), "telr.com": ("Telr", "payments", False),
    # website builders (context only)
    "wixstatic.com": ("Wix", "builder", False), "squarespace": ("Squarespace", "builder", False),
    "wp-content": ("WordPress", "builder", False), "cdn.shopify.com": ("Shopify", "builder", False),
    "webflow": ("Webflow", "builder", False),
}
