// Host-source palette adapter: same seeds/palette mapping as themes/context.tsx.
// No host services, persistence, font URLs, or theme custom CSS are started here.
import {nousTheme, DEFAULT_TYPOGRAPHY} from '@/themes/presets';
export function applyHostTheme(mode) {
  const c = mode === 'dark' ? nousTheme.darkColors : nousTheme.colors;
  const vars = {
    '--theme-foreground':c.foreground, '--theme-primary':c.primary,
    '--theme-secondary':c.secondary, '--theme-accent-soft':c.accent,
    '--theme-midground':c.midground ?? c.ring, '--theme-warm':c.primary,
    '--theme-background-seed':c.background, '--theme-sidebar-seed':c.sidebarBackground ?? c.background,
    '--theme-card-seed':c.card, '--theme-elevated-seed':c.popover, '--theme-bubble-seed':c.userBubble ?? c.popover,
    '--dt-primary-foreground':c.primaryForeground, '--dt-secondary-foreground':c.secondaryForeground,
    '--dt-accent-foreground':c.accentForeground, '--dt-border':c.border, '--dt-input':c.input,
    '--dt-ring':c.ring, '--dt-muted':c.muted, '--dt-composer-ring':c.composerRing ?? c.midground ?? c.ring,
    '--dt-destructive':c.destructive, '--dt-destructive-foreground':c.destructiveForeground,
    '--dt-font-sans':DEFAULT_TYPOGRAPHY.fontSans, '--dt-font-mono':DEFAULT_TYPOGRAPHY.fontMono
  };
  for (const [key,value] of Object.entries(vars)) document.documentElement.style.setProperty(key,value);
  document.documentElement.dataset.hermesTheme = 'nous';
  document.documentElement.dataset.hermesMode = mode;
}
