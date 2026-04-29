import { useEffect, useRef, useState } from "react";
import { api, type IotSensorRow } from "../api";

const ROOM_INFO: Record<string, { crop: string; zone: string }> = {
  "GR-01": { crop: "Butterhead Lettuce",     zone: "Leafy Greens" },
  "GR-02": { crop: "Red Leaf Lettuce",       zone: "Leafy Greens" },
  "GR-03": { crop: "Genovese Basil",         zone: "Herbs" },
  "GR-04": { crop: "Cilantro Herb",          zone: "Herbs" },
  "GR-05": { crop: "Radish Microgreens",     zone: "Microgreens" },
  "GR-06": { crop: "Pea Shoot Microgreens",  zone: "Microgreens" },
};

type SensorCfg = { label: string; icon: string; decimals: number };
const SENSOR_CFG: Record<string, SensorCfg> = {
  temperature:   { label: "Temperature", icon: "🌡", decimals: 1 },
  humidity:      { label: "Humidity",    icon: "💧", decimals: 1 },
  soil_moisture: { label: "Soil",        icon: "🌱", decimals: 1 },
  light:         { label: "Light",       icon: "☀",  decimals: 0 },
  co2:           { label: "CO₂",        icon: "💨", decimals: 0 },
  ph:            { label: "pH",          icon: "⚗",  decimals: 2 },
  ec:            { label: "EC",          icon: "⚡", decimals: 2 },
};
const SENSOR_ORDER = ["temperature","humidity","soil_moisture","light","co2","ph","ec"];

const STATUS_COLOR: Record<string, string> = {
  NOMINAL: "#21c07a", CAUTION: "#f2b840", ALERT: "#ef4a4a",
};

function roomStatus(s: IotSensorRow[]): "NOMINAL"|"CAUTION"|"ALERT" {
  if (s.some(r=>r.status==="ALERT")) return "ALERT";
  if (s.some(r=>r.status==="CAUTION")) return "CAUTION";
  return "NOMINAL";
}

// ── Arc gauge (SVG semi-circle speedometer) ──────────────────────────────────

function ArcGauge({ s, history }: { s: IotSensorRow; history: number[] }) {
  const CX = 50, CY = 50, R = 42;
  const L = Math.PI * R;                       // ≈ 131.95
  const arc = `M ${CX-R} ${CY} A ${R} ${R} 0 0 0 ${CX+R} ${CY}`;

  const lo = s.disp_min ?? 0, hi = s.disp_max ?? 100;
  const rng = hi - lo || 1;
  const frac = (v: number) => Math.max(0, Math.min(1, (v - lo) / rng));

  const val    = s.value ?? 0;
  const vf     = frac(val);
  const wlo    = s.warn_min  != null ? frac(s.warn_min)  : null;
  const whi    = s.warn_max  != null ? frac(s.warn_max)  : null;
  const color  = STATUS_COLOR[s.status ?? "NOMINAL"];
  const cfg    = SENSOR_CFG[s.sensor_type];

  // Tick position on arc at fraction f: (CX - R·cos(π·f), CY - R·sin(π·f))
  function tickLine(f: number, col: string, ri = 36, ro = 47) {
    const a = Math.PI * f;
    return (
      <line
        x1={CX - ri * Math.cos(a)} y1={CY - ri * Math.sin(a)}
        x2={CX - ro * Math.cos(a)} y2={CY - ro * Math.sin(a)}
        stroke={col} strokeWidth="1.5" strokeOpacity="0.8"
      />
    );
  }

  return (
    <div style={{ display:"flex", flexDirection:"column", alignItems:"center", width:100 }}>
      <svg viewBox="0 0 100 60" width="100" height="60" style={{ display:"block", overflow:"visible" }}>
        {/* Track */}
        <path d={arc} fill="none" stroke="#1d2544" strokeWidth="8" strokeLinecap="round" />

        {/* Nominal zone */}
        {wlo!=null && whi!=null && (
          <path d={arc} fill="none" stroke="rgba(33,192,122,0.22)" strokeWidth="8"
            strokeDasharray={`0 ${wlo*L} ${(whi-wlo)*L} 9999`} />
        )}

        {/* Value fill — animate via stroke-dashoffset */}
        <path d={arc} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${L} ${L}`}
          strokeDashoffset={`${(1-vf)*L}`}
          style={{ transition:"stroke-dashoffset 0.55s ease, stroke 0.3s" }} />

        {/* Threshold tick marks */}
        {wlo!=null && tickLine(wlo, "#f2b840")}
        {whi!=null && tickLine(whi, "#f2b840")}
        {s.alert_min!=null && tickLine(frac(s.alert_min), "#ef4a4a")}
        {s.alert_max!=null && tickLine(frac(s.alert_max), "#ef4a4a")}

        {/* Value + unit text */}
        <text x="50" y="43" textAnchor="middle" fontSize="13" fontWeight="700"
          fill={color} fontFamily="'JetBrains Mono',Menlo,Consolas,monospace">
          {val.toFixed(cfg?.decimals ?? 1)}
        </text>
        <text x="50" y="54" textAnchor="middle" fontSize="7" fill="#8a97b8">
          {s.unit}
        </text>
      </svg>

      {/* Sparkline */}
      <Sparkline values={history} color={color} />

      {/* Label */}
      <div style={{ fontSize:10, color:"#8a97b8", marginTop:2, textAlign:"center", lineHeight:1.3 }}>
        {cfg?.icon} {cfg?.label}
      </div>
    </div>
  );
}

// ── Sparkline SVG ─────────────────────────────────────────────────────────────

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) {
    return <svg width="80" height="16" style={{ display:"block" }} />;
  }
  const W = 80, H = 16;
  const lo = Math.min(...values), hi = Math.max(...values);
  const rng = hi - lo || 1;
  const pts = values.map((v, i) =>
    `${(i/(values.length-1))*W},${H - ((v-lo)/rng)*H}`
  ).join(" ");
  const area = `M 0,${H} L ${pts.replace(/,/g, " L ").split(" L ").slice(1).join(" L ")} L ${W},${H} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display:"block" }}>
      <path d={`M 0,${H} L ${pts}`} fill="none" stroke={color}
        strokeWidth="1.5" strokeOpacity="0.75" strokeLinejoin="round" />
      <path d={`M 0,${H} L ${pts} L ${W},${H} Z`} fill={color} fillOpacity="0.1" />
    </svg>
  );
}

// ── Room card ─────────────────────────────────────────────────────────────────

function RoomCard({
  roomId, sensors, history,
}: {
  roomId: string;
  sensors: IotSensorRow[];
  history: Map<string, number[]>;
}) {
  const info   = ROOM_INFO[roomId] ?? { crop: roomId, zone: "Unknown" };
  const status = roomStatus(sensors);
  const color  = STATUS_COLOR[status];
  const alerts  = sensors.filter(s=>s.status==="ALERT").length;
  const cautions= sensors.filter(s=>s.status==="CAUTION").length;
  const lastTs  = sensors.reduce<string|null>((b,s)=>(!s.event_ts?b:!b||s.event_ts>b?s.event_ts:b),null);
  const ordered = SENSOR_ORDER
    .map(t=>sensors.find(s=>s.sensor_type===t))
    .filter(Boolean) as IotSensorRow[];

  return (
    <div style={{
      background:"var(--panel)", border:"1px solid var(--border)",
      borderTop:`3px solid ${color}`, borderRadius:12, padding:"14px 16px",
    }}>
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:12 }}>
        <div>
          <div style={{ fontWeight:700, fontSize:15, letterSpacing:0.5 }}>{roomId}</div>
          <div style={{ fontSize:12, color:"var(--muted)", marginTop:2 }}>
            {info.zone} · {info.crop}
          </div>
        </div>
        <div style={{ textAlign:"right" }}>
          <StatusBadge status={status} />
          {(alerts>0||cautions>0) && (
            <div style={{ fontSize:11, marginTop:4 }}>
              {alerts>0   && <span style={{color:"#ef4a4a"}}>⚠ {alerts}A </span>}
              {cautions>0 && <span style={{color:"#f2b840"}}>◆ {cautions}W</span>}
            </div>
          )}
        </div>
      </div>

      {/* Gauge grid: 4 columns, auto-wraps to 2 rows for 7 sensors */}
      {ordered.length === 0 ? (
        <p style={{ color:"var(--muted)", fontSize:12 }}>Waiting for first reading…</p>
      ) : (
        <div style={{
          display:"grid",
          gridTemplateColumns:"repeat(4, 1fr)",
          gap:"8px 4px",
          justifyItems:"center",
        }}>
          {ordered.map(s => (
            <ArcGauge key={s.sensor_type} s={s}
              history={history.get(`${roomId}:${s.sensor_type}`) ?? []} />
          ))}
        </div>
      )}

      {lastTs && (
        <div style={{ fontSize:10, color:"var(--muted)", marginTop:8,
          borderTop:"1px solid var(--border)", paddingTop:6 }}>
          Last reading · {new Date(lastTs).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: "NOMINAL"|"CAUTION"|"ALERT" }) {
  const cfg = {
    NOMINAL:{ bg:"rgba(33,192,122,0.15)",  text:"#21c07a", label:"OK" },
    CAUTION:{ bg:"rgba(242,184,64,0.15)",  text:"#f2b840", label:"CAUTION" },
    ALERT:  { bg:"rgba(239,74,74,0.20)",   text:"#ef4a4a", label:"ALERT" },
  }[status];
  return (
    <span style={{
      display:"inline-block", padding:"3px 10px", borderRadius:10,
      fontSize:11, fontWeight:700, letterSpacing:0.5,
      background:cfg.bg, color:cfg.text,
    }}>
      {status==="ALERT"&&"⚠ "}{cfg.label}
    </span>
  );
}

// ── Farm overview header ───────────────────────────────────────────────────────

function FarmOverview({ roomMap }: { roomMap: Map<string, IotSensorRow[]> }) {
  const rooms   = Array.from(roomMap.entries()).sort(([a],[b])=>a.localeCompare(b));
  const total   = rooms.length;
  const alerts  = rooms.filter(([,s])=>roomStatus(s)==="ALERT").length;
  const cautions= rooms.filter(([,s])=>roomStatus(s)==="CAUTION").length;

  return (
    <div style={{
      background:"var(--panel)", border:"1px solid var(--border)",
      borderRadius:12, padding:"12px 20px", marginBottom:16,
      display:"flex", alignItems:"center", gap:28, flexWrap:"wrap",
    }}>
      <div style={{ display:"flex", gap:28 }}>
        {[
          { label:"Rooms",   value:total,              color:"var(--text)" },
          { label:"Alerts",  value:alerts,             color:alerts>0?"#ef4a4a":"var(--muted)" },
          { label:"Cautions",value:cautions,           color:cautions>0?"#f2b840":"var(--muted)" },
          { label:"Nominal", value:total-alerts-cautions, color:"#21c07a" },
        ].map(({label,value,color})=>(
          <div key={label}>
            <div style={{ fontSize:10, color:"var(--muted)", textTransform:"uppercase", letterSpacing:1 }}>{label}</div>
            <div style={{ fontSize:26, fontWeight:700, color, lineHeight:1.1 }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ display:"flex", gap:10, flexWrap:"wrap", marginLeft:"auto" }}>
        {rooms.map(([roomId,sensors])=>{
          const st = roomStatus(sensors);
          const col = STATUS_COLOR[st];
          return (
            <div key={roomId} title={`${roomId} — ${st}`}
              style={{ display:"flex", flexDirection:"column", alignItems:"center", gap:4 }}>
              <div style={{
                width:16, height:16, borderRadius:"50%", background:col,
                boxShadow:st!=="NOMINAL"?`0 0 8px ${col}`:"none",
                animation:st==="ALERT"?"pulse 1.5s ease infinite":"none",
              }} />
              <span style={{ fontSize:9, color:"var(--muted)", letterSpacing:0.3 }}>{roomId}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Root ───────────────────────────────────────────────────────────────────────

const HISTORY_LEN = 40;

export default function IotFieldsPanel({ tick }: { tick: number }) {
  const [rows, setRows]   = useState<IotSensorRow[]>([]);
  const histRef = useRef<Map<string, number[]>>(new Map());

  useEffect(() => {
    api.iotSensors().then(newRows => {
      newRows.forEach(r => {
        if (r.value == null) return;
        const key = `${r.room_id}:${r.sensor_type}`;
        const buf = histRef.current.get(key) ?? [];
        buf.push(r.value);
        if (buf.length > HISTORY_LEN) buf.shift();
        histRef.current.set(key, [...buf]);
      });
      setRows(newRows);
    }).catch(() => setRows([]));
  }, [tick]);

  const roomMap = new Map<string, IotSensorRow[]>();
  rows.forEach(r => {
    if (!roomMap.has(r.room_id)) roomMap.set(r.room_id, []);
    roomMap.get(r.room_id)!.push(r);
  });
  const sorted = Array.from(roomMap.entries()).sort(([a],[b])=>a.localeCompare(b));

  return (
    <div>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
      `}</style>

      {roomMap.size === 0 ? (
        <p style={{ color:"var(--muted)", padding:16 }}>
          No IoT data yet — start the IoT simulator or wait for Lakeflow to sync the first sensor readings.
        </p>
      ) : (
        <>
          <FarmOverview roomMap={roomMap} />
          <div style={{
            display:"grid",
            gridTemplateColumns:"repeat(auto-fill, minmax(380px, 1fr))",
            gap:14,
          }}>
            {sorted.map(([roomId, sensors]) => (
              <RoomCard key={roomId} roomId={roomId}
                sensors={sensors} history={histRef.current} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
