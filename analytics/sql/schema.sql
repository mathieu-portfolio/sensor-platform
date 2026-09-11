CREATE TABLE events (
    run_id UBIGINT NOT NULL,
    run_generation UBIGINT NOT NULL,
    stream_sequence UBIGINT NOT NULL,
    event_time_seconds FLOAT NOT NULL,
    event_type VARCHAR NOT NULL,
    sensor_id INTEGER,
    sensor_generation UBIGINT,
    scan_sequence UBIGINT,
    measurement_count UBIGINT,
    seed UINTEGER,
    PRIMARY KEY (run_id, stream_sequence)
);
CREATE TABLE scans (
    run_id UBIGINT NOT NULL,
    run_generation UBIGINT NOT NULL,
    stream_sequence UBIGINT NOT NULL,
    acquisition_time_seconds FLOAT NOT NULL,
    sensor_id INTEGER NOT NULL,
    sensor_generation UBIGINT NOT NULL,
    scan_sequence UBIGINT NOT NULL,
    measurement_count UBIGINT NOT NULL,
    PRIMARY KEY (run_id, stream_sequence),
    UNIQUE (run_id, run_generation, sensor_id, sensor_generation, scan_sequence)
);
CREATE TABLE measurements (
    run_id UBIGINT NOT NULL,
    run_generation UBIGINT NOT NULL,
    stream_sequence UBIGINT NOT NULL,
    acquisition_time_seconds FLOAT NOT NULL,
    sensor_id INTEGER NOT NULL,
    sensor_generation UBIGINT NOT NULL,
    scan_sequence UBIGINT NOT NULL,
    detection_id INTEGER NOT NULL,
    x FLOAT NOT NULL,
    y FLOAT NOT NULL,
    confidence FLOAT NOT NULL,
    uncertainty_radius FLOAT NOT NULL,
    PRIMARY KEY (run_id, run_generation, sensor_id, sensor_generation, detection_id)
);
