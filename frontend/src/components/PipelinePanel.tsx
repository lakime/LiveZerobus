import { useEffect, useState } from "react";
import { api, type Summary } from "../api";

// Stage definitions
const STAGES = [
  { id:"bronze",   label:"Bronze Delta Δ", sub:"Append-only Zerobus streams",  color:"#ff8c42" },
  { id:"silver",   label:"Silver Streams", sub:"Dedup · schema enforce · CDC",  color:"#a8c4e0" },
  { id:"gold",     label:"Gold MVs",       sub:"Lakeflow materialized views",   color:"#f2b840" },
  { id:"lakebase", label:"Lakebase",       sub:"Postgres · 15s snapshot sync",  color:"#21c07a" },
  { id:"api",      label:"FastAPI",        sub:"REST endpoints · OAuth tokens", color:"#4ea1ff" },
  { id:"ui",       label:"React UI",       sub:"Live dashboard · 3s refresh",   color:"#b06bff" },
];

const SIM_DEFS = [
  { id:"inventory", label:"Inventory", color:"#4ea1ff" },
  { id:"suppliers", label:"Quotes",    color:"#21c07a" },
  { id:"demand",    label:"Demand",    color:"#f2b840" },
  { id:"commodity", label:"Commodity", color:"#b06bff" },
  { id:"sap",       label:"SAP P2P",  color:"#ff8c42" },
  { id:"iot",       label:"IoT",       color:"#00d4aa" },
];

const W = 680, CX = W / 2;
const STAGE_W = 320, STAGE_H = 48;
const stageX = CX - STAGE_W / 2;

// y positions
const SIM_Y   = 20;
const ZB_Y    = 110;
const GAP     = 84; // between stage boxes
const stageY  = (i: number) => ZB_Y + i * GAP;
const TOTAL_H = stageY(STAGES.length) + STAGE_H + 30;

// Sim node x positions (evenly spread)
const SIM_XS = SIM_DEFS.map((_, i) => 40 + i * ((W - 80) / (SIM_DEFS.length - 1)));

function isLive(summary: Summary | null): boolean {
  if (!summary?.last_market_tick) return false;
  return Date.now() - new Date(summary.last_market_tick).getTime() < 60_000;
}

// Animated particles along a vertical path
function FlowParticles({
  x, y1, y2, color, n = 3, dur = 1.6, active = true,
}: {
  x: number; y1: number; y2: number; color: string;
  n?: number; dur?: number; active?: boolean;
}) {
  if (!active) return null;
  return (
    <>
      {Array.from({ length: n }, (_, i) => (
        <circle key={i} r="3" fill={color} opacity="0.85">
          <animateMotion
            dur={`${dur}s`}
            repeatCount="indefinite"
            begin={`${(i / n) * dur}s`}
            path={`M ${x} ${y1} L ${x} ${y2}`}
          />
          <animate attributeName="opacity" values="0;0.9;0.9;0" keyTimes="0;0.1;0.85;1"
            dur={`${dur}s`} repeatCount="indefinite" begin={`${(i / n) * dur}s`} />
        </circle>
      ))}
    </>
  );
}

// Animated particles from sim nodes converging to Zerobus
function SimParticles({ sx, color, active }: { sx: number; color: string; active: boolean }) {
  if (!active) return null;
  const path = `M ${sx} ${SIM_Y + 22} Q ${sx} ${ZB_Y - 10} ${CX} ${ZB_Y}`;
  return (
    <>
      {[0, 0.5, 1.0].map((delay, i) => (
        <circle key={i} r="2.5" fill={color} opacity="0.8">
          <animateMotion dur="1.8s" repeatCount="indefinite"
            begin={`${delay}s`} path={path} />
          <animate attributeName="opacity" values="0;0.85;0.85;0"
            keyTimes="0;0.1;0.85;1" dur="1.8s" repeatCount="indefinite"
            begin={`${delay}s`} />
        </circle>
      ))}
    </>
  );
}

function StageBox({
  label, sub, color, y, active,
}: {
  label: string; sub: string; color: string; y: number; active: boolean;
}) {
  const glowOp = active ? 0.3 : 0;
  return (
    <g>
      {/* Glow / active halo */}
      <rect x={stageX - 4} y={y - 4} width={STAGE_W + 8} height={STAGE_H + 8}
        rx="14" fill={color} opacity={glowOp}
        style={{ filter:"blur(6px)", transition:"opacity 0.5s" }} />
      {/* Box */}
      <rect x={stageX} y={y} width={STAGE_W} height={STAGE_H}
        rx="10" fill="#141a2f" stroke={active ? color : "#263056"} strokeWidth="1.5"
        style={{ transition:"stroke 0.3s" }} />
      {/* Left accent bar */}
      <rect x={stageX} y={y} width="4" height={STAGE_H} rx="2" fill={color} opacity="0.9" />
      {/* Live dot */}
      {active && (
        <circle cx={stageX + STAGE_W - 14} cy={y + STAGE_H / 2} r="4" fill={color}>
          <animate attributeName="opacity" values="1;0.3;1" dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
      {/* Text */}
      <text x={stageX + 18} y={y + 18} fontSize="13" fontWeight="700" fill="#eaf0ff">{label}</text>
      <text x={stageX + 18} y={y + 34} fontSize="10" fill="#8a97b8">{sub}</text>
    </g>
  );
}

export default function PipelinePanel({ tick }: { tick: number }) {
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, [tick]);

  const live = isLive(summary);
  const pipeColor = "#4ea1ff";

  // vertical pipe color between stages
  const pipeSegColor = (i: number) => STAGES[i]?.color ?? pipeColor;

  return (
    <div style={{ display:"flex", gap:24, flexWrap:"wrap" }}>
      {/* ── SVG pipeline ── */}
      <div style={{
        background:"var(--panel)", border:"1px solid var(--border)",
        borderRadius:12, padding:"16px 20px", flex:"1 1 500px",
      }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:12 }}>
          <h3 style={{ margin:0, fontSize:12, color:"var(--muted)", textTransform:"uppercase", letterSpacing:"1.2px" }}>
            Data Pipeline
          </h3>
          <span style={{
            fontSize:11, padding:"3px 10px", borderRadius:10, fontWeight:700,
            background: live ? "rgba(33,192,122,0.15)" : "rgba(138,151,184,0.15)",
            color: live ? "#21c07a" : "var(--muted)",
          }}>
            {live ? "● LIVE" : "○ WAITING"}
          </span>
        </div>

        <svg viewBox={`0 0 ${W} ${TOTAL_H}`} width="100%" style={{ display:"block", maxWidth:W }}>
          <defs>
            <marker id="arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#4ea1ff" opacity="0.6" />
            </marker>
          </defs>

          {/* ── Simulator nodes ── */}
          {SIM_DEFS.map((sim, i) => {
            const sx = SIM_XS[i];
            return (
              <g key={sim.id}>
                <circle cx={sx} cy={SIM_Y + 11} r="18" fill="#1a2140"
                  stroke={sim.color} strokeWidth="1.5" />
                <text x={sx} y={SIM_Y + 10} textAnchor="middle"
                  fontSize="7.5" fontWeight="700" fill={sim.color} dominantBaseline="middle">
                  {sim.label}
                </text>
                {/* Funnel line to Zerobus */}
                <line x1={sx} y1={SIM_Y + 29} x2={CX} y2={ZB_Y}
                  stroke={sim.color} strokeWidth="1" strokeOpacity={live ? 0.45 : 0.2}
                  strokeDasharray="4 3">
                  <animate attributeName="stroke-dashoffset" from="14" to="0"
                    dur="1s" repeatCount="indefinite" />
                </line>
                <SimParticles sx={sx} color={sim.color} active={live} />
              </g>
            );
          })}

          {/* ── Zerobus box ── */}
          <g>
            <rect x={CX - 130} y={ZB_Y} width={260} height={42} rx="10"
              fill="#141a2f" stroke={live ? "#4ea1ff" : "#263056"} strokeWidth="1.5" />
            <rect x={CX - 130} y={ZB_Y} width="4" height={42} rx="2" fill="#4ea1ff" opacity="0.9" />
            {live && (
              <circle cx={CX + 116} cy={ZB_Y + 21} r="4" fill="#4ea1ff">
                <animate attributeName="opacity" values="1;0.3;1" dur="1.4s" repeatCount="indefinite" />
              </circle>
            )}
            <text x={CX - 113} y={ZB_Y + 16} fontSize="13" fontWeight="700" fill="#eaf0ff">Zerobus gRPC</text>
            <text x={CX - 113} y={ZB_Y + 30} fontSize="10" fill="#8a97b8">Append-only event streams → Delta</text>
          </g>

          {/* ── Stage boxes + connectors ── */}
          {STAGES.map((stage, i) => {
            const y = stageY(i) + 42 + 10; // offset below zerobus group
            const prevY = i === 0
              ? ZB_Y + 42
              : stageY(i - 1) + 42 + 10 + STAGE_H;
            const connY1 = prevY;
            const connY2 = y;

            return (
              <g key={stage.id}>
                {/* Connector line */}
                <line x1={CX} y1={connY1} x2={CX} y2={connY2}
                  stroke={stage.color} strokeWidth="2" strokeOpacity={live ? 0.5 : 0.2}
                  strokeDasharray="5 4">
                  <animate attributeName="stroke-dashoffset" from="18" to="0"
                    dur={`${0.9 + i * 0.1}s`} repeatCount="indefinite" />
                </line>

                {/* Particles flowing down */}
                <FlowParticles x={CX} y1={connY1 + 4} y2={connY2 - 4}
                  color={stage.color} n={2} dur={1.2 + i * 0.1} active={live} />

                <StageBox label={stage.label} sub={stage.sub}
                  color={stage.color} y={y} active={live} />
              </g>
            );
          })}
        </svg>
      </div>

      {/* ── Right panel: stage descriptions + stats ── */}
      <div style={{ flex:"0 0 240px", display:"flex", flexDirection:"column", gap:10 }}>
        <div style={{
          background:"var(--panel)", border:"1px solid var(--border)",
          borderRadius:12, padding:"14px 16px",
        }}>
          <div style={{ fontSize:11, color:"var(--muted)", textTransform:"uppercase",
            letterSpacing:"1px", marginBottom:10 }}>Pipeline stats</div>
          {[
            { label:"Inbound (unread)",    value: summary?.inbound_unprocessed ?? "—" },
            { label:"BUY_NOW last 5m",     value: summary?.buy_now_last_5m ?? "—" },
            { label:"POs open",            value: summary?.po_drafts_open ?? "—" },
            { label:"Spend pending (1h)",  value: summary?.spend_pending_1h_usd != null
                ? `$${(summary.spend_pending_1h_usd as number).toFixed(0)}` : "—" },
            { label:"SKUs below reorder",  value: summary?.skus_below_reorder ?? "—" },
          ].map(({ label, value }) => (
            <div key={label} style={{ display:"flex", justifyContent:"space-between",
              padding:"6px 0", borderBottom:"1px dashed #1d2544", fontSize:12 }}>
              <span style={{ color:"var(--muted)" }}>{label}</span>
              <span style={{ fontWeight:600 }}>{String(value)}</span>
            </div>
          ))}
        </div>

        <div style={{
          background:"var(--panel)", border:"1px solid var(--border)",
          borderRadius:12, padding:"14px 16px", flex:1,
        }}>
          <div style={{ fontSize:11, color:"var(--muted)", textTransform:"uppercase",
            letterSpacing:"1px", marginBottom:10 }}>Stages</div>
          {[
            { label:"Simulators → Zerobus", color:"#4ea1ff", desc:"6 event streams" },
            ...STAGES.map(s => ({ label:s.label, color:s.color, desc:s.sub })),
          ].map(({ label, color, desc }) => (
            <div key={label} style={{ display:"flex", gap:8, alignItems:"flex-start",
              marginBottom:10, fontSize:12 }}>
              <div style={{ width:3, height:28, borderRadius:2, background:color,
                flexShrink:0, marginTop:2 }} />
              <div>
                <div style={{ fontWeight:600 }}>{label}</div>
                <div style={{ fontSize:10, color:"var(--muted)" }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
