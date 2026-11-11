-- Created using a19b0fd Store before WP9 changes.
BEGIN TRANSACTION;
CREATE TABLE drafts (
                id TEXT PRIMARY KEY, definition TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created_ts REAL NOT NULL, expires_ts REAL NOT NULL, origin TEXT,
                replaces TEXT, note TEXT, sample TEXT, preview TEXT, decided_ts REAL, budget TEXT, source_state TEXT NOT NULL DEFAULT '{}', preview_calls INTEGER NOT NULL DEFAULT 0, preview_due REAL NOT NULL DEFAULT 0, preview_allowed INTEGER NOT NULL DEFAULT 0, auth TEXT, preview_lease TEXT, diff TEXT, base_definition TEXT, preview_error TEXT);
INSERT INTO "drafts" VALUES('pd_4f13541bb4','{"pulse": 1, "id": "old", "title": "Old", "source": {"kind": "discord.invite", "params": {"invite": "nousresearch", "voice": false}}, "every": "10m", "ring": {"components": [{"metric": "online", "weight": 70, "type": "delta", "baseline": "median", "window": "24h", "floor": 25, "sensitivity": 0.2, "direction": "both"}, {"metric": "members", "weight": 20, "type": "delta", "baseline": "oldest", "window": "24h", "floor": 100, "sensitivity": 0.01, "direction": "both"}, {"metric": "voice_channels", "weight": 10, "type": "level", "full_at": 5}]}, "capsule": {"metric": "online", "label": "{value} online", "fill": "baseline"}, "lines": [{"metric": "members", "show": "delta", "label": "Net {delta} members \u00b7 {window}", "hide_when_zero": false}, {"metric": "voice_channels", "label": "{value} active voice channels", "show": "value", "hide_when_zero": false}], "icon": "source", "link": "https://discord.gg/nousresearch"}','pending',1000.0,605800.0,'{}','old',NULL,NULL,NULL,NULL,'{"hosts": ["cdn.discordapp.com", "discord.com"], "req_per_hour": 6.0, "req_per_hour_display": 6}','{}',0,0.0,0,NULL,NULL,'','{"pulse": 1, "id": "old", "title": "Old", "source": {"kind": "discord.invite", "params": {"invite": "nousresearch", "voice": false}}, "every": "10m", "ring": {"components": [{"metric": "online", "weight": 70, "type": "delta", "baseline": "median", "window": "24h", "floor": 25, "sensitivity": 0.2, "direction": "both"}, {"metric": "members", "weight": 20, "type": "delta", "baseline": "oldest", "window": "24h", "floor": 100, "sensitivity": 0.01, "direction": "both"}, {"metric": "voice_channels", "weight": 10, "type": "level", "full_at": 5}]}, "capsule": {"metric": "online", "label": "{value} online", "fill": "baseline"}, "lines": [{"metric": "members", "show": "delta", "label": "Net {delta} members \u00b7 {window}", "hide_when_zero": false}, {"metric": "voice_channels", "label": "{value} active voice channels", "show": "value", "hide_when_zero": false}], "icon": "source", "link": "https://discord.gg/nousresearch"}',NULL);
CREATE TABLE gates (key TEXT PRIMARY KEY, until_ts REAL NOT NULL);
INSERT INTO "gates" VALUES('remote:discord.com',1234.0);
CREATE TABLE hermes_events (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
                status TEXT, origin TEXT);
CREATE TABLE hermes_open (
                kind TEXT NOT NULL, key TEXT NOT NULL, ts REAL NOT NULL,
                expires_ts REAL NOT NULL, origin TEXT, PRIMARY KEY(kind,key));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO "meta" VALUES('schema_version','1');
CREATE TABLE pulses (
                id TEXT PRIMARY KEY, definition TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0,
                next_due REAL NOT NULL DEFAULT 0, last_ok_ts REAL,
                backoff_until REAL NOT NULL DEFAULT 0, error TEXT,
                failures INTEGER NOT NULL DEFAULT 0, source_state TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}', approved_via TEXT NOT NULL DEFAULT 'rest',
                created_ts REAL NOT NULL, updated_ts REAL NOT NULL, budget TEXT);
INSERT INTO "pulses" VALUES('old','{"pulse": 1, "id": "old", "title": "Old", "source": {"kind": "discord.invite", "params": {"invite": "nousresearch", "voice": false}}, "every": "10m", "ring": {"components": [{"metric": "online", "weight": 70, "type": "delta", "baseline": "median", "window": "24h", "floor": 25, "sensitivity": 0.2, "direction": "both"}, {"metric": "members", "weight": 20, "type": "delta", "baseline": "oldest", "window": "24h", "floor": 100, "sensitivity": 0.01, "direction": "both"}, {"metric": "voice_channels", "weight": 10, "type": "level", "full_at": 5}]}, "capsule": {"metric": "online", "label": "{value} online", "fill": "baseline"}, "lines": [{"metric": "members", "show": "delta", "label": "Net {delta} members \u00b7 {window}", "hide_when_zero": false}, {"metric": "voice_channels", "label": "{value} active voice channels", "show": "value", "hide_when_zero": false}], "icon": "source", "link": "https://discord.gg/nousresearch"}',0,0.0,1000.0,0.0,NULL,0,'{"invite_due": 1600}','{}','rest',1000.0,1000.0,'{"hosts": ["cdn.discordapp.com", "discord.com"], "req_per_hour": 6.0, "req_per_hour_display": 6}');
CREATE TABLE samples (
                pulse_id TEXT NOT NULL, ts REAL NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(pulse_id, ts));
INSERT INTO "samples" VALUES('old',1000.0,'{"ts": 1000, "metrics": {"online": 42, "members": 100}}');
CREATE INDEX hermes_events_ts ON hermes_events(ts);
COMMIT;