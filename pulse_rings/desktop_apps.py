"""Curated desktop-notification app aliases. Code-owned data only; no I/O.

Each alias maps to exact Windows AppUserModelIDs (AUMIDs) as stored in
NotificationHandler.PrimaryId. Definitions can select an alias or pass an exact
`app_ids` entry, but can never extend this table. IDs marked verified were
observed in a real Windows 11 notification store; the others are the apps'
published/default IDs and simply report "not registered" when absent.
"""

# alias: (display name, bundled brand slug or None, AUMIDs)
APPS = {
    'discord': ('Discord', 'discord', (
        'com.squirrel.Discord.Discord',             # verified
        'com.squirrel.DiscordPTB.DiscordPTB',
        'com.squirrel.DiscordCanary.DiscordCanary')),
    'teams': ('Microsoft Teams', None, (
        'MSTeams_8wekyb3d8bbwe!MSTeams',             # verified
        'com.squirrel.Teams.Teams')),
    'outlook': ('Outlook', None, (
        'Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookforWindows',  # verified
        'Microsoft.Office.OUTLOOK.EXE.15')),
    'slack': ('Slack', None, ('com.squirrel.slack.slack',)),
    'whatsapp': ('WhatsApp', 'whatsapp', ('5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App',)),  # verified
    'telegram': ('Telegram', 'telegram', (
        'TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram.TelegramDesktop.Store',
        'Telegram.TelegramDesktop')),
    'signal': ('Signal', 'signal', ('org.whispersystems.signal-desktop',)),
    'spotify': ('Spotify', 'spotify', ('Spotify.desktop.client',)),  # verified
    'chrome': ('Google Chrome', 'googlechrome', ('Chrome',)),         # verified
    'edge': ('Microsoft Edge', None, ('MSEdge',)),                     # verified
    'claude': ('Claude', 'claude', ('Claude_pzs8sxrjxfjjc!Claude',)),  # verified
    'hermes': ('Hermes', 'hermes', ('com.nousresearch.hermes',)),      # verified
    'phone_discord': ('Discord (phone)', 'discord', (
        'Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.discord',)),  # verified
}
ALIASES = list(APPS)
MAX_APPS = 8
# Aliases whose AUMID is also the app's Start-menu identity, so Windows can open the
# app from it. Each was observed in Get-StartApps on a real Windows 11 PC. Left out on
# purpose: phone_discord (a Phone Link notification channel, not an app), spotify (its
# Start identity is an install path) and slack/signal (not yet observed).
LAUNCHABLE = frozenset({'discord', 'teams', 'outlook', 'whatsapp', 'telegram', 'chrome', 'edge', 'claude', 'hermes'})


def app_ids(params):
    """Exact, de-duplicated (case-insensitive) AUMIDs selected by params."""
    out, seen = [], set()
    for alias in params.get('apps', []) or []:
        for aumid in APPS.get(alias, ('', None, ()))[2]:
            if aumid.lower() not in seen:
                seen.add(aumid.lower())
                out.append(aumid)
    for aumid in params.get('app_ids', []) or []:
        if isinstance(aumid, str) and aumid.lower() not in seen:
            seen.add(aumid.lower())
            out.append(aumid)
    return out


def entries(params):
    """One AUMID group per selected app entry (alias variants or one exact id)."""
    groups = [list(APPS[a][2]) for a in params.get('apps', []) or [] if a in APPS]
    return groups + [[a] for a in params.get('app_ids', []) or [] if isinstance(a, str)]


def names(params):
    """Human labels in definition order: alias display names, then exact ids."""
    labels = [APPS[a][0] for a in params.get('apps', []) or [] if a in APPS]
    return labels + [a for a in params.get('app_ids', []) or [] if isinstance(a, str)]


def brand(params):
    for alias in params.get('apps', []) or []:
        if alias in APPS and APPS[alias][1]:
            return APPS[alias][1]
    return None


def launch_target(params, seen=()):
    """(display name, exact AUMID) of the one app a notifications pulse may open, else None.

    Only a pulse that watches exactly one curated, launchable alias has a target: an
    exact `app_ids` entry is never opened, and with several apps a click would be a
    guess. `seen` is the AUMIDs the notification store reported for this pulse; the
    variant actually present on this PC is the one opened (Discord, not Canary).
    """
    apps = params.get('apps', []) or []
    if len(apps) != 1 or params.get('app_ids') or apps[0] not in LAUNCHABLE:
        return None
    name, _, aumids = APPS[apps[0]]
    present = {a.lower() for a in seen if isinstance(a, str)}
    for aumid in aumids:
        if aumid.lower() in present:
            return name, aumid
    return None


PREVIEW_TARGET = ' · message previews'


def target(params):
    """Exact disclosure target. Desktop recomputes the same string to gate Approve.

    Opt-in message previews change the target, so a desktop that does not know about
    them cannot approve such a pulse, and turning them on is a new approval.
    """
    selected = list(params.get('apps', []) or []) + list(params.get('app_ids', []) or [])
    return 'this PC · ' + ', '.join(str(item) for item in selected) + (
        PREVIEW_TARGET if params.get('preview') is True else '')
