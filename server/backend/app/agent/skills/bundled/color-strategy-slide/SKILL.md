---
name: color-strategy-slide
description: Strategy& brand recipe — palette, typography, layout principles, and voice for Strategy&-branded slides. Apply before calling CreateSlide so the deck looks on-brand.
argumentHint: "<optional: deck topic or audience>"
aliases: [strategy-and, strategyand]
whenToUse: When the user asks for a  Strategy& deck, or when no brand is named. Invoke once before the first CreateSlide call; the values apply to every CreateSlide call for the rest of the conversation unless the user changes brands.
---

/* =============================================
   GPT Slide Generator — Trimmed Stylesheet
   Strategy& Consulting Design System
   ============================================= */
 
/* ===== BASE VARIABLES & SLIDE STRUCTURE ===== */
.slide {
  --slide-w: 960px;
  --slide-min-h: 540px;
  --left-x: 35px;
  --title-w: 890px;
  --subtitle-w: 890px;
  --title-y: 30px;
  --subtitle-y: 101px;
  --frame-y: 137px;
  --frame-w: 890px;
  --right-bound: 925px;
 
  /* Text */
  --heading: #111111;
  --body: #222222;
  --muted: #4A4F57;
 
  /* Accent */
  --accent: #8E1E1E;
  --accent-hover: #A32020;
  --accent-soft: #F8E3E3;
  --on-accent: #FFFFFF;
 
  /* Status */
  --success: #059669;
  --success-soft: rgba(16, 185, 129, 0.15);
  --warning: #d97706;
  --warning-soft: rgba(245, 158, 11, 0.15);
  --danger: #dc2626;
  --danger-soft: rgba(220, 38, 38, 0.15);
  --info: #3b82f6;
  --info-soft: rgba(59, 130, 246, 0.15);
 
  /* Surfaces */
  --page: #FFFFFF;
  --surface: #F7F9FB;
  --surface-alt: #EEF2F6;
  --border: #E6E9EE;
 
  /* Aliases */
  --maroon: var(--accent);
  --red: var(--accent-hover);
  --rose: var(--accent-soft);
  --main: var(--heading);
  --secondary: var(--body);
  --meta: var(--muted);
  --coal: var(--muted);
  --zone1: var(--surface);
  --zone2: var(--surface-alt);
  --bg: var(--page);
 
  /* Spacing */
  --gH: 16px;
  --gV: 12px;
  --radius: 4px;
 
  /* Base styles */
  position: relative;
  width: var(--slide-w);
  height: var(--slide-min-h);
  background: var(--page);
  box-sizing: border-box;
  overflow: hidden;
  font-family: Arial, sans-serif;
  color: var(--body);
}
 
/* ===== GLOBAL RULES ===== */
.slide * { box-sizing: border-box; max-width: 100%; }
.slide [class*="row"], .slide [class*="col"], .slide [class*="grid"], .slide [class*="container"] { min-width: 0; min-height: 0; }
.slide .title, .slide .subtitle, .slide h1, .slide h2, .slide h3, .slide h4, .slide h5, .slide h6 { word-wrap: break-word; overflow-wrap: break-word; white-space: normal; }
.slide p, .slide li, .slide span { word-wrap: break-word; overflow-wrap: break-word; hyphens: auto; }
 
/* Semantic token mappings */
.slide h1, .slide h2, .slide h3, .slide h4, .slide h5, .slide h6, .slide .title, .slide [class*="title"] { color: var(--heading); }
.slide p, .slide li, .slide td, .slide span:not([class*="title"]):not([class*="label"]) { color: var(--body); }
.slide .subtitle, .slide .caption, .slide .meta, .slide small, .slide [class*="label"], .slide [class*="desc"] { color: var(--muted); }
.slide .card, .slide .box, .slide .panel, .slide .cell, .slide [class*="card"], .slide [class*="box"], .slide [class*="block"], .slide [class*="item"]:not(li):not(.ba-item), .slide [class*="cell"] { border-color: var(--border); }
.slide .card-icon-circle, .slide .timeline-marker, .slide .kpi-value, .slide .value, .slide .number { color: var(--accent); }
 
/* ===== TITLE, SUBTITLE, FRAME, FOOTER ===== */
.slide .title {
  position: absolute;
  left: var(--left-x);
  top: var(--title-y);
  width: var(--title-w);
  font: 400 28px/1.2 Georgia, serif;
  font-weight: 400 !important;
  color: var(--main);
  margin: 0;
}
.slide .title strong, .slide .title b, .slide h1.title strong, .slide h1.title b { font-weight: 400 !important; }
 
.slide .subtitle {
  position: absolute;
  left: var(--left-x);
  top: var(--subtitle-y);
  width: var(--subtitle-w);
  font: 700 18px/1.2 Arial, sans-serif;
  color: var(--red);
  margin: 0;
}
 
.slide .frame {
  position: absolute;
  left: var(--left-x);
  top: var(--frame-y);
  width: var(--frame-w);
  height: 353px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}
 
.slide footer.footer {
  position: absolute;
  bottom: 0;
  left: var(--left-x);
  width: 890px;
  padding-bottom: 14px;
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--meta);
}
 
/* ===== SLIDE MASTERS ===== */
.slide.master-standard { }
.slide.master-standard:not(:has(.title)):not(:has(h1)) .frame { top: 35px; height: 455px; }
.slide.master-standard:has(.title):not(:has(.subtitle)):not(:has(h2)) .frame,
.slide.master-standard:has(h1):not(:has(.subtitle)):not(:has(h2)) .frame { top: 80px; height: 410px; }
 
.slide.master-blank .frame { top: 35px; height: 455px; }
.slide.master-blank .title, .slide.master-blank .subtitle { display: none; }
 
.slide.master-titleOnly .subtitle { display: none; }
.slide.master-titleOnly .frame { top: 90px; height: 400px; }
 
.slide.master-cover .footer { display: none; }
 
/* ===== COVER ===== */
.slide.cover-slide .frame { top: 140px; height: auto; display: flex; flex-direction: column; justify-content: flex-start; gap: 16px; }
.slide .cover-category { font: 700 18px/1.2 Arial, sans-serif; color: var(--red); text-transform: uppercase; letter-spacing: 1px; }
.slide .cover-title { font: 400 42px/1.15 Georgia, serif; color: var(--main); max-width: 700px; }
.slide .cover-branding { position: absolute; left: var(--left-x); bottom: 50px; font: 700 16px/1 Arial, sans-serif; color: var(--meta); }
.slide .cover-date { position: absolute; right: var(--left-x); bottom: 50px; font: 400 13px/1 Arial, sans-serif; color: var(--meta); }