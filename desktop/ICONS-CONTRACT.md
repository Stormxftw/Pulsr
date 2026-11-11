# WP8 resolved icons — renderer contract

Every active status row includes `icon_resolved` (additive; `icon_url` keeps its
legacy Discord identity/behavior). Draft/error rows carry an offline fallback.

- `{kind: "raster", url: "/icons/<key>"}`: obtain through `ctx.rest(url)` relative
  to the plugin API, **not** a browser `fetch` or a remote image URL. The response
  remains `{icon_data: "data:image/png|webp|jpeg;base64,…"}`. Validate that data-URI
  prefix and base64 alphabet before using an `<img>`. Cache by `url`; on failure
  use title initials. Keys: `sha256-` + 64 lowercase hex digits or the unchanged
  Discord `<guild>-<hash>` form. GET never fetches upstream. Immutable private cache.
- `{kind: "brand", slug, hex, path}`: render an SVG with `viewBox="0 0 24 24"`
  containing **one `<path d={path} fill={adaptiveFill}>`**. `hex` is six hex digits,
  without `#`. Shared `BrandGlyph` compares the brand colour with the actual
  composited solid background using WCAG sRGB relative luminance. At ≥3:1 keep
  the brand path colour; below 3:1 use theme ink (black/white adaptive fallback
  only when that ink also fails). Preserve the original hex in the outline accent
  (`--pr-brand-accent`) and `data-brand-hex`. Re-evaluate on SDK appearance and
  pulse/preview theme changes. The picker and live/preview cards share this rule.
  `path` is bundled, strictly validated path data; no XML/markup.
  Never use `innerHTML`, `dangerouslySetInnerHTML`, `<use>`, external SVGs, remote
  URLs, style strings, or eval. `slug: "hermes"` uses the original bundled winged
  H monogram; it has the same shape as the other brands but is not a Simple Icons
  entry. Do not derive an upstream URL from any slug.
- `{kind: "emoji", text}` and `{kind: "initials", text}`: render text nodes only.

Source precedence: cached Discord guild icon; approved GitHub repo owner/org
avatar; MCP `Tool.icons` before `serverInfo.icons`; Hermes monogram; offline
GitHub/Discord brand; title initials. Explicit `{brand}`, `{emoji}`, `{url}` and
legacy string forms override source choice. Failed explicit URLs fall back to the
kind brand/initials. Multiple feeds follow the hero block’s first metric/component feed; they do not
select another feed by source-type precedence.

MCP raster data URIs are local-only; HTTPS candidates require exact membership in
the **persisted** approval budget. Within each MCP icon list prefer advertised
PNG/WebP/JPEG, then sizes closest to 64–128 px; theme is neutral. Invalid/unsafe
icons are skipped. All network rasters are ≤256 KiB and Content-Type/magic-checked;
SVG is never accepted from the network. No renderer egress.

The deliberately reduced Simple Icons 16.36.0 bundle contains 3,465 icons
(4,811,947 bytes). Entire records matching crypto_mining/tunnel_service in
slug/title/upstream source are excluded under scripts/ARTWORK-SCOPE.md; this is
not a complete upstream release. Excluded slugs/reasons are in the license file.
Artwork: CC0-1.0; see `pulse_rings/BRANDS-LICENSE.md` for upstream CC0 and trademark
notices. Trademark rights are not granted; logos do not imply endorsement.
