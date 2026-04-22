CREATE TABLE IF NOT EXISTS epochs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name    TEXT    UNIQUE NOT NULL,
    created_at      REAL    NOT NULL,
    topo_image_url  TEXT
);

CREATE TABLE IF NOT EXISTS metric_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch_id     INTEGER NOT NULL REFERENCES epochs(id) ON DELETE CASCADE,
    metric_type  TEXT    NOT NULL,
    device       TEXT    NOT NULL,
    labels_json  TEXT    NOT NULL DEFAULT '{}',
    value        REAL    NOT NULL,
    timestep     INTEGER NOT NULL,
    timestamp    REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_epoch_type_device
    ON metric_samples(epoch_id, metric_type, device, timestep);

CREATE TABLE IF NOT EXISTS metric_type_meta (
    metric_type   TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    unit          TEXT,
    chart_kind    TEXT NOT NULL DEFAULT 'line',
    sort_order    INTEGER NOT NULL DEFAULT 100
);
