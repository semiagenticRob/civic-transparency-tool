# Eyes on Arvada — Image Generation Guide

Peter Rabbit uses this guide to generate consistent header images for the Eyes on Arvada newsletter. Follow it exactly for every new image.

---

## Output Spec

| Property | Value |
|----------|-------|
| Dimensions | 1200 × 630 px |
| Format | JPEG, quality 92 |
| Use | Newsletter header images (Beehiiv) |

---

## Visual Style

**Every image must match this aesthetic:**

- **Background:** Warm cream or light beige (`#F5F0E8` range)
- **Palette:** Muted earth tones — terracotta orange, warm brown, dusty sage green, soft charcoal. No neon, no pure primaries.
- **Style:** Flat editorial illustration. Clean line art. No gradients, no 3D, no photorealism.
- **Mood:** Calm, civic, community-centered. Think city council meeting, neighborhood event, public infrastructure — not corporate, not alarming.
- **Figures:** Diverse Arvada residents — mix of ages, backgrounds. Shown in human-scale indoor civic settings.
- **No text in the image.** Ever.
- **No logos, badges, or overlays** — those are added by Beehiiv.
- **Lighting:** Warm indoor light, often afternoon sun through windows.

**Reference:** The established look is a flat illustration style used in quality local civic journalism — editorial, not infographic.

---

## Technical Approach

**API:** Cloudflare Workers AI — Flux.1 Schnell  
**Credentials:** Stored in `/workspace/agent/credentials.md` under "Cloudflare Workers AI — Image Generation"  
**Endpoint:** `https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell`

**Constraint:** Width and height must be divisible by 8. Since 630 is not, generate at **1200 × 632**, then crop to **1200 × 630** using sharp.

---

## Generation Script

```javascript
// gen-newsletter-image.mjs
const ACCOUNT_ID = "<from credentials.md>";
const API_TOKEN = "<from credentials.md>";
const ENDPOINT = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell`;

const prompt = `<your prompt here>`;

const response = await fetch(ENDPOINT, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${API_TOKEN}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ prompt, num_steps: 8, width: 1200, height: 632 })
});

const data = await response.json();
if (data.result?.image) {
  const { writeFileSync } = await import('fs');
  const buf = Buffer.from(data.result.image, 'base64');
  writeFileSync('/tmp/newsletter-raw.jpg', buf);
}

// Crop to 1200x630 with sharp
const sharp = require('/pnpm/global/5/.pnpm/sharp@0.34.5/node_modules/sharp/lib/index.js');
sharp('/tmp/newsletter-raw.jpg')
  .resize(1200, 630, { position: 'centre' })
  .jpeg({ quality: 92 })
  .toFile('/workspace/agent/<output-name>.jpg', (err, info) => {
    if (err) throw err;
    console.log('Done:', info);
  });
```

---

## Prompt Formula

Use this structure for every prompt. Fill in the bracketed sections:

```
Flat editorial illustration for a civic newsletter. Warm cream beige background. 
Muted earth tones: terracotta orange, warm brown, dusty sage green, soft charcoal. 
Clean line art style.

[SCENE: Describe the setting and figures. Arvada civic context. 
Specific action happening. Who is present. What they're doing.]

[DETAIL: One or two visual details that make it specific to this story — 
a map on the wall, a sign, a specific object, a view out the window.]

Calm informative community-centered mood. Flat illustration style used in civic 
journalism. No text in image.
```

---

## Prompt Examples

### Wildfire Readiness (May 2026)
```
Flat editorial illustration for a civic newsletter. Warm cream beige background. 
Muted earth tones: terracotta orange, warm brown, dusty sage green, soft charcoal. 
Clean line art style.

A community meeting room in Arvada Colorado. A fire department captain in navy 
uniform stands at the front presenting a large illustrated map on the wall showing 
evacuation routes and fire danger zones. A diverse group of neighbors seated in 
rows — older residents, a parent with a child, a young professional — all engaged 
and attentive. Warm afternoon light through tall windows. The map uses orange and 
red for fire danger zones, soft lines for evacuation routes.

Calm informative community-centered mood. Flat illustration style used in civic 
journalism. No text in image.
```

---

## Workflow Checklist

1. [ ] Read the newsletter issue topic and identify the main civic scene to illustrate
2. [ ] Write prompt using the formula above — specific to this story, no generic stock-photo energy
3. [ ] Generate at 1200×632 via Cloudflare Flux
4. [ ] Crop to 1200×630 with sharp
5. [ ] Send via `send_file` with brief caption
6. [ ] Save final image to `/workspace/agent/<topic-slug>.jpg` for reference

---

## Common Mistakes to Avoid

- **Infographic style** — charts, icons in boxes, data tables. That's not the style.
- **Dark backgrounds** — the base is always warm cream/beige.
- **Photorealism** — flat illustration only.
- **Generic scenes** — always Arvada-specific. City hall, neighborhood streets, community rooms.
- **Text in image** — never. Beehiiv handles all text overlays.
- **Saturated colors** — earth tones only. When in doubt, desaturate.
