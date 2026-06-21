# Evidence Capture SOP — Seller Center order-history exhibits

The packet embeds one Seller Center **order-history** screenshot per filable claim as the
Gate-3 proof (the auto-approval line). These exhibits go to the merchant and, on appeal, to
TikTok — so they must show **only the order evidence**, never the analyst's desktop.

The generator has a defensive crop (trims browser chrome on stray full-window captures), but
that is a **safety net**. The durable fix is capturing clean at the source. Follow this for
every real (non-fixture) merchant capture.

## Why this matters
A raw full-window screenshot leaks analyst context into a client/legal document: personal
bookmarks, open tab titles, browser extensions, and assistant sidebars (e.g. Gemini). That is
unprofessional and a privacy/infosec problem. The order's customer fields are already masked by
TikTok — leave those exactly as TikTok masks them; **do not** add or remove masking yourself.

## Capture steps
1. **Clean profile.** Use an Incognito/Private window or a dedicated capture browser profile
   with **no** personal bookmarks bar, **no** pinned/open personal tabs, **no** extensions, and
   **no** assistant sidebar/overlay (disable Gemini/Copilot side panels).
2. **Navigate** to: Seller Center → Orders → Manage orders → open the order → scroll to
   **Order history**.
3. **Frame the content only.** Capture just the order-detail + **Order history** panel. Do not
   include the browser chrome (tabs/bookmarks/address bar) or any window border. Prefer a
   region/element capture over a full-window grab.
4. **The Order-history resolution line must be legible** — specifically the auto-approval line
   ("…awaiting approval for too long, and has now been auto-approved") with its timestamp. If
   it is scrolled off, capture so it is visible; a claim's exhibit is incomplete without it.
5. **Consistent zoom** (100%) and a consistent window width across all captures, so pages look
   uniform in the packet.
6. **Leave masking as-is.** Customer name/address/contact appear as TikTok masks them. Never
   un-mask; never hand-redact real data into the image.
7. **Name the file `<order_id>.png`** and drop it in the run's screenshots directory. The packet
   auto-matches by the resolution's `evidence_ref` (set to `<order_id>.png`).

## What good looks like
- Frame contains: Seller Center order header, the SKU/RAF line, and the **Order history** panel
  with the auto-approval line + timestamp.
- Frame does **not** contain: browser tabs, bookmarks bar, address bar, OS window chrome,
  assistant sidebars/overlays, or any other merchant's data.

## If you must use a full-window capture
The packet will crop the top browser-chrome band and the right-edge assistant overlay
(`chrome_crop_top` / `chrome_crop_right`, applied only to landscape full-window captures). This
is a fallback — it can only remove margins, never recover content it had to cut. Re-capture
clean whenever possible; spot-check the rendered exhibit page before sending.

## Future automation
When the merchant grants **Order API** access, pull the order-history resolution line
programmatically instead of screenshotting — same Gate-3 field, no capture hygiene needed.
