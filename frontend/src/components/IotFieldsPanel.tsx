import { useEffect, useState } from "react";
import { api, type IotSensorRow } from "../api";

// Room metadata displayed on cards
const ROOM_INFO: Record<string, { crop: string; zone: string }> = {
  "GR-01": { crop: "Butterhead Lettuce",    zone: "Leafy Greens" },
  "GR-02": { crop: "Red Leaf Lettuce",      zone: "Leafy Greens" },
  "GR-03": { crop: "Genovese Basil",        zone: "Herbs" },
  "GR-04": { crop: "Cilantro Herb",         zone: "Herbs" },
  "GR-05": { crop: "Radish Microgreens",    zone: "Microgreens" },
  "GR-06": { crop: "Pea Shoot Microgreens", zone: "Microgreens" },
};

type SensorCfg = { label: string; icon: string; decimals: number };
const SENSOR_CFG: Record<string, SensorCfg> = {
  temperature:   { label: "Temperature", icon: "🌡", decimals: 1 },
  humidity:      { label: "Humidity",    icon: "💧", decimals: 1 },
  soil_moisture: { label: "Soil",        icon: "🌱", decimals: 1 },
  light:         { label: "Light",       icon: "☀",  decimals: 0 },
  co2:           { label: "CO₂",         icon: "💨", decimals: 0 },
  ph:            { label: "pH",          icon: "⚗",  decimals: 2 },
  ec:            { label: "EC",          icon: "⚡", decimals: 2 },
};

const SENSOR_ORDER = ["temperature", "humidity", "soil_moisture", "light", "co2", "ph", "ec"];

const STATUS_COLOR: Record<string, string> = {
  NOMINAL: "#21c07a",
  CAUTION: "#f2b840",
  ALERT:   "#ef4a4a",
};

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

function roomStatus(sensors: IotSensorRow[]): "NOMINAL" | "CAUTION" | "ALERT" {
  if (sensors.some((s) => s.status === "ALERT")) return "ALERT";
  if (sensors.some((s) => s.status === "CAUTION")) return "CAUTION";
  return "NOMINAL";
}

// ─── Sensor gauge bar ────────────────────────────────────────────────────────

function SensorGauge({ s }: { s: IotSensorRow }) {
  const cfg = SENSOR_CFG[s.sensor_type];
  const val = s.value ?? 0;
  const dMin = s.disp_min ?? 0;
  const dMax = s.disp_max ?? 100;
  const range = dMax - dMin || 1;

  const fillPct  = clamp(((val - dMin) / range) * 100, 0, 100);
  const wMinPct  = s.warn_min  != null ? clamp(((s.warn_min  - dMin) / range) * 100, 0, 100) : null;
  const wMaxPct  = s.warn_max  != null ? clamp(((s.warn_max  - dMin) / range) * 100, 0, 100) : null;
  const aMinPct  = s.alert_min != null ? clamp(((s.alert_min - dMin) / range) * 100, 0, 100) : null;
  const aMaxPct  = s.alert_max != null ? clamp(((s.alert_max - dMin) / range) * 100, 0, 100) : null;

  const color = STATUS_COLOR[s.status ?? "NOMINAL"];

  return (
    <div style={{ marginBottom: 10 }}>
      {/* Row: label left, value right */}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
        <span style={{ color: "var(--muted)" }}>
          {cfg?.icon}&nbsp;{cfg?.label}
        </span>
        <span style={{ color, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
          {val.toFixed(cfg?.decimals ?? 1)}&nbsp;{s.unit}
        </span>
      </div>

      {/* Gauge track */}
      <div style={{
        position: "relative", height: 7, borderRadius: 4,
        background: "var(--border)", overflow: "hidden",
      }}>
        {/* Nominal-zone highlight (between warn bounds) */}
        {wMinPct != null && wMaxPct != null && (
          <div style={{
            position: "absolute",
            left: `${wMinPct}%`, width: `${wMaxPct - wMinPct}%`,
            height: "100%",
            background: "rgba(33,192,122,0.18)",
          }} />
        )}
        {/* Alert-zone danger tint (below alert_min and above alert_max) */}
        {aMinPct != null && (
          <div style={{
            position: "absolute",
            left: 0, width: `${aMinPct}%`,
            height: "100%", background: "rgba(239,74,74,0.12)",
          }} />
        )}
        {aMaxPct != null && (
          <div style={{
            position: "absolute",
            left: `${aMaxPct}%`, width: `${100 - aMaxPct}%`,
            height: "100%", background: "rgba(239,74,74,0.12)",
          }} />
        )}
        {/* Value fill */}
        <div style={{
          position: "absolute", left: 0,
          width: `${fillPct}%`, height: "100%",
          background: color, borderRadius: 4,
          transition: "width 0.5s ease, background 0.3s",
        }} />
      </div>

      {/* Threshold tick marks drawn below the track */}
      <div style={{ position: "relative", height: 5 }}>
        {[
          { pct: wMinPct,  col: "#f2b840" },
          { pct: wMaxPct,  col: "#f2b840" },
          { pct: aMinPct,  col: "#ef4a4a" },
          { pct: aMaxPct,  col: "#ef4a4a" },
        ].filter(({ pct }) => pct != null).map(({ pct, col }, i) => (
          <div key={i} style={{
            position: "absolute",
            left: `calc(${pct}% - 1px)`,
            top: 0, width: 2, height: 5,
            background: col, opacity: 0.7, borderRadius: 1,
          }} />
        ))}
      </div>
    </div>
  );
}

// ─── Single room card ─────────────────────────────────────────────────────────

function RoomCard({ roomId, sensors }: { roomId: string; sensors: IotSensorRow[] }) {
  const info = ROOM_INFO[roomId] ?? { crop: roomId, zone: "Unknown" };
  const status = roomStatus(sensors);
  const color = STATUS_COLOR[status];
  const alertCount  = sensors.filter((s) => s.status === "ALERT").length;
  const cautionCount= sensors.filter((s) => s.status === "CAUTION").length;
  const lastTs = sensors.reduce<string | null>((best, s) => {
    if (!s.event_ts) return best;
    return !best || s.event_ts > best ? s.event_ts : best;
  }, null);

  const orderedSensors = SENSOR_ORDER
    .map((t) => sensors.find((s) => s.sensor_type === t))
    .filter(Boolean) as IotSensorRow[];

  return (
    <div style={{
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderLeft: `4px solid ${color}`,
      borderRadius: 12,
      padding: "14px 16px",
      display: "flex", flexDirection: "column",
    }}>
      {/* Card header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: 0.5 }}>{roomId}</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            {info.zone} · {info.crop}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <StatusBadge status={status} />
          {(alertCount > 0 || cautionCount > 0) && (
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
              {alertCount > 0 && <span style={{ color: "#ef4a4a" }}>⚠ {alertCount} alert{alertCount > 1 ? "s" : ""} </span>}
              {cautionCount > 0 && <span style={{ color: "#f2b840" }}>◆ {cautionCount} warn{cautionCount > 1 ? "s" : ""}</span>}
            </div>
          )}
        </div>
      </div>

      {/* Sensor gauges */}
      <div style={{ flex: 1 }}>
        {orderedSensors.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 12, margin: 0 }}>Waiting for first reading…</p>
        ) : (
          orderedSensors.map((s) => <SensorGauge key={s.sensor_type} s={s} />)
        )}
      </div>

      {/* Timestamp footer */}
      {lastTs && (
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6, borderTop: "1px solid var(--border)", paddingTop: 6 }}>
          Last reading: {new Date(lastTs).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: "NOMINAL" | "CAUTION" | "ALERT" }) {
  const cfg = {
    NOMINAL: { label: "OK",      bg: "rgba(33,192,122,0.15)",   text: "#21c07a" },
    CAUTION: { label: "CAUTION", bg: "rgba(242,184,64,0.15)",   text: "#f2b840" },
    ALERT:   { label: "ALERT",   bg: "rgba(239,74,74,0.20)",    text: "#ef4a4a" },
  }[status];
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 10,
      fontSize: 11, fontWeight: 700, letterSpacing: 0.5,
      background: cfg.bg, color: cfg.text,
    }}>
      {status === "ALERT" && "⚠ "}{cfg.label}
    </span>
  );
}

// ─── Farm overview mini-map ───────────────────────────────────────────────────

function FarmOverview({ roomMap }: { roomMap: Map<string, IotSensorRow[]> }) {
  const rooms = Array.from(roomMap.entries()).sort(([a], [b]) => a.localeCompare(b));
  const total   = rooms.length;
  const alerts  = rooms.filter(([, s]) => roomStatus(s) === "ALERT").length;
  const cautions= rooms.filter(([, s]) => roomStatus(s) === "CAUTION").length;

  return (
    <div style={{
      background: "var(--panel)", border: "1px solid var(--border)",
      borderRadius: 12, padding: "12px 16px", marginBottom: 16,
      display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap",
    }}>
      {/* KPIs */}
      <div style={{ display: "flex", gap: 24 }}>
        <Kpi label="Rooms" value={total} color="var(--text)" />
        <Kpi label="Alerts"   value={alerts}   color={alerts   > 0 ? "#ef4a4a" : "var(--muted)"} />
        <Kpi label="Cautions" value={cautions} color={cautions > 0 ? "#f2b840" : "var(--muted)"} />
        <Kpi label="Nominal"  value={total - alerts - cautions} color="#21c07a" />
      </div>

      {/* Room status dots */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {rooms.map(([roomId, sensors]) => {
          const st = roomStatus(sensors);
          const col = STATUS_COLOR[st];
          return (
            <div key={roomId} title={`${roomId} — ${st}`} style={{
              display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
            }}>
              <div style={{
                width: 14, height: 14, borderRadius: "50%",
                background: col,
                boxShadow: st === "ALERT" ? `0 0 8px ${col}` : "none",
                animation: st === "ALERT" ? "pulse 1.5s ease infinite" : "none",
              }} />
              <span style={{ fontSize: 9, color: "var(--muted)", letterSpacing: 0.3 }}>{roomId}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Kpi({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color, lineHeight: 1.1 }}>{value}</div>
    </div>
  );
}

// ─── Panel root ───────────────────────────────────────────────────────────────

export default function IotFieldsPanel({ tick }: { tick: number }) {
  const [rows, setRows] = useState<IotSensorRow[]>([]);

  useEffect(() => {
    api.iotSensors().then(setRows).catch(() => setRows([]));
  }, [tick]);

  // Group by room_id
  const roomMap = new Map<string, IotSensorRow[]>();
  rows.forEach((r) => {
    if (!roomMap.has(r.room_id)) roomMap.set(r.room_id, []);
    roomMap.get(r.room_id)!.push(r);
  });

  const sortedRooms = Array.from(roomMap.entries()).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div>
      {/* Inject keyframe for alert pulse */}
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>

      {roomMap.size === 0 ? (
        <p style={{ color: "var(--muted)" }}>
          No IoT data yet — start the IoT simulator (<code>python simulators/iot_simulator.py</code>)
          or wait for the Lakeflow pipeline to sync the first sensor readings.
        </p>
      ) : (
        <>
          <FarmOverview roomMap={roomMap} />

          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 14,
          }}>
            {sortedRooms.map(([roomId, sensors]) => (
              <RoomCard key={roomId} roomId={roomId} sensors={sensors} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
