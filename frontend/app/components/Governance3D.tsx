"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { Cpu, Database, ShieldAlert } from "lucide-react";
import type { BiasAudit, BiasAuditDimension, CapabilitySnapshot } from "../../lib/api";

type Governance3DProps = {
  snapshot: CapabilitySnapshot | null;
  biasAudit: BiasAudit | null;
  measuredSavingsPct?: number | null;
};

const COLORS = {
  amd: "#ff2f46",
  fireworks: "#31c7ff",
  cache: "#38d66b",
  compliance: "#3ce886",
  amber: "#ffb020",
  shell: "#5D1C6A",
};

export default function Governance3D({
  snapshot,
  biasAudit,
  measuredSavingsPct = null,
}: Governance3DProps) {
  const routes = snapshot?.routing ?? [];
  const providerLabel = snapshot?.active_provider?.replaceAll("_", " ") ?? "deterministic";
  const batchRoute = routes.find((route) => route.task_type.includes("batch"));
  const liveAllowed = routes.filter((route) => route.live_call_allowed).length;
  const auditedDimensions =
    biasAudit?.dimensions && biasAudit.dimensions.length > 0
      ? biasAudit.dimensions
      : fallbackBiasDimensions();
  const worstDimension = auditedDimensions.reduce((worst, current) =>
    current.adverse_impact_ratio < worst.adverse_impact_ratio ? current : worst
  );
  const alertCopy =
    biasAudit?.available && biasAudit.headline
      ? biasAudit.headline
      : `Synthetic ATS fixture expected alert: ${worstDimension.dimension} ratio ${worstDimension.adverse_impact_ratio.toFixed(
          2
        )} is below 0.80.`;

  return (
    <section className="overflow-hidden rounded-2xl border border-brand-purple/20 bg-[#130719] text-white shadow-sm">
      <div className="grid grid-cols-1 lg:grid-cols-[1.25fr_0.95fr]">
        <div className="relative min-h-[420px] border-b border-white/10 lg:border-b-0 lg:border-r">
          <GridBackdrop />
          <div className="absolute left-5 top-5 z-10 max-w-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-peach">
              <Cpu size={16} />
              Hybrid Routing Topology
            </div>
            <p className="mt-1 text-xs leading-relaxed text-white/65">
              Semantic cache, AMD-local, and Fireworks-cloud paths rendered from the capability
              engine. This is topology evidence, not a performance claim.
            </p>
          </div>
          <Canvas camera={{ position: [0, 0.45, 5.8], fov: 46 }}>
            <color attach="background" args={["#130719"]} />
            <ambientLight intensity={0.45} />
            <pointLight position={[0, 2.8, 3]} intensity={18} color="#ffffff" />
            <RoutingScene />
          </Canvas>
          <div className="absolute bottom-5 left-5 right-5 z-10 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
            <TopologyChip label="Active route" value={providerLabel} tone="cyan" />
            <TopologyChip label="Live calls" value={String(liveAllowed)} tone="green" />
            <TopologyChip
              label="Batch path"
              value={batchRoute?.selected_provider ?? "gated"}
              tone="amber"
            />
          </div>
        </div>

        <div className="relative min-h-[420px]">
          <GridBackdrop />
          <div className="absolute left-5 top-5 z-10 max-w-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-peach">
              <ShieldAlert size={16} />
              Bias Audit Radar
            </div>
            <p className="mt-1 text-xs leading-relaxed text-white/65">
              Synthetic ATS data intentionally violates the Four-Fifths rule. Race impact pierces
              the safe boundary so the compliance alert is visible.
            </p>
          </div>
          <Canvas camera={{ position: [0, 0.1, 4.8], fov: 44 }}>
            <color attach="background" args={["#130719"]} />
            <ambientLight intensity={0.55} />
            <pointLight position={[1.8, 2.8, 3]} intensity={12} color="#ffffff" />
            <BiasRadarScene dimensions={auditedDimensions} />
          </Canvas>
          <div className="absolute bottom-5 left-5 right-5 z-10 space-y-2 text-xs">
            <div className="rounded-lg border border-red-400/40 bg-red-500/15 px-3 py-2 text-red-100">
              COMPLIANCE ALERT · {alertCopy}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <TopologyChip
                label="Cost evidence"
                value={
                  measuredSavingsPct === null
                    ? "not measured"
                    : `${measuredSavingsPct.toFixed(1)}% measured`
                }
                tone={measuredSavingsPct === null ? "amber" : "green"}
              />
              <TopologyChip
                label="ATS records"
                value={biasAudit?.available ? String(biasAudit.record_count) : "fixture gated"}
                tone="purple"
              />
            </div>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t border-white/10 px-5 py-3 text-xs text-white/60">
        <Database size={14} className="text-brand-peach" />
        Generated data lives under backend/sample_data/hackathon; production claims still require
        measured evidence artifacts.
      </div>
    </section>
  );
}

function RoutingScene() {
  const group = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(clock.elapsedTime * 0.18) * 0.18;
    }
  });

  return (
    <group ref={group}>
      <Node position={[0, 0.1, 0]} color="#ffffff" emissive="#CA5995" radius={0.36} />
      <Node position={[-1.85, -0.6, -0.35]} color={COLORS.cache} emissive={COLORS.cache} />
      <Node position={[1.7, -0.45, -0.2]} color={COLORS.amd} emissive={COLORS.amd} />
      <Node position={[0.55, 1.15, -0.55]} color={COLORS.fireworks} emissive={COLORS.fireworks} />
      <Beam start={[0, 0.1, 0]} end={[-1.85, -0.6, -0.35]} color={COLORS.cache} />
      <Beam start={[0, 0.1, 0]} end={[1.7, -0.45, -0.2]} color={COLORS.amd} />
      <Beam start={[0, 0.1, 0]} end={[0.55, 1.15, -0.55]} color={COLORS.fireworks} />
      {Array.from({ length: 30 }, (_, index) => (
        <DataParticle key={index} index={index} />
      ))}
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0.1, 0]}>
        <torusGeometry args={[2.15, 0.01, 12, 96]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.18} />
      </mesh>
    </group>
  );
}

function BiasRadarScene({ dimensions }: { dimensions: BiasAuditDimension[] }) {
  const group = useRef<THREE.Group>(null);
  const metrics = useMemo(
    () =>
      dimensions.map((dimension, index) => ({
        label: dimension.dimension,
        ratio: dimension.adverse_impact_ratio,
        angle: 0.35 + index * ((Math.PI * 2) / Math.max(dimensions.length, 1)),
      })),
    [dimensions]
  );

  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = clock.elapsedTime * 0.18;
      group.current.rotation.x = Math.sin(clock.elapsedTime * 0.12) * 0.1;
    }
  });

  return (
    <group ref={group}>
      <mesh>
        <sphereGeometry args={[1.12, 48, 24]} />
        <meshBasicMaterial color={COLORS.compliance} transparent opacity={0.12} wireframe />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.12, 0.012, 12, 96]} />
        <meshBasicMaterial color={COLORS.compliance} transparent opacity={0.65} />
      </mesh>
      {metrics.map((metric) => {
        const violates = metric.ratio < 0.8;
        const radius = violates ? 1.52 : 0.78 + metric.ratio * 0.28;
        return (
          <group key={metric.label}>
            <mesh
              position={[
                Math.cos(metric.angle) * radius,
                violates ? 0.52 : 0.12,
                Math.sin(metric.angle) * radius,
              ]}
            >
              <sphereGeometry args={[violates ? 0.105 : 0.075, 20, 20]} />
              <meshStandardMaterial
                color={violates ? "#ff405f" : COLORS.compliance}
                emissive={violates ? "#ff405f" : COLORS.compliance}
                emissiveIntensity={violates ? 1.8 : 1.1}
              />
            </mesh>
            {violates && (
              <Beam
                start={[0, 0, 0]}
                end={[
                  Math.cos(metric.angle) * radius,
                  0.52,
                  Math.sin(metric.angle) * radius,
                ]}
                color="#ff405f"
                opacity={0.55}
              />
            )}
          </group>
        );
      })}
    </group>
  );
}

function fallbackBiasDimensions(): BiasAuditDimension[] {
  return [
    {
      dimension: "gender",
      reference_group: "M",
      reference_rate: 0.96,
      lowest_group: "F",
      lowest_rate: 0.91,
      adverse_impact_ratio: 0.95,
      threshold: 0.8,
      violates_four_fifths_rule: false,
      groups: [],
    },
    {
      dimension: "age_group",
      reference_group: "31-50",
      reference_rate: 0.72,
      lowest_group: "51+",
      lowest_rate: 0.62,
      adverse_impact_ratio: 0.86,
      threshold: 0.8,
      violates_four_fifths_rule: false,
      groups: [],
    },
    {
      dimension: "race",
      reference_group: "White",
      reference_rate: 0.7,
      lowest_group: "Black",
      lowest_rate: 0.5,
      adverse_impact_ratio: 0.71,
      threshold: 0.8,
      violates_four_fifths_rule: true,
      groups: [],
    },
  ];
}

function Node({
  position,
  color,
  emissive,
  radius = 0.25,
}: {
  position: [number, number, number];
  color: string;
  emissive: string;
  radius?: number;
}) {
  const mesh = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (mesh.current) {
      const scale = 1 + Math.sin(clock.elapsedTime * 2.2 + position[0]) * 0.045;
      mesh.current.scale.setScalar(scale);
    }
  });
  return (
    <mesh ref={mesh} position={position}>
      <sphereGeometry args={[radius, 32, 32]} />
      <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={1.5} />
    </mesh>
  );
}

function Beam({
  start,
  end,
  color,
  opacity = 0.34,
}: {
  start: [number, number, number];
  end: [number, number, number];
  color: string;
  opacity?: number;
}) {
  const curve = useMemo(
    () =>
      new THREE.CatmullRomCurve3([
        new THREE.Vector3(...start),
        new THREE.Vector3((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 + 0.18, -0.12),
        new THREE.Vector3(...end),
      ]),
    [start, end]
  );
  const points = useMemo(() => curve.getPoints(32), [curve]);
  const geometry = useMemo(() => new THREE.BufferGeometry().setFromPoints(points), [points]);
  const material = useMemo(
    () => new THREE.LineBasicMaterial({ color, transparent: true, opacity }),
    [color, opacity]
  );
  const line = useMemo(() => new THREE.Line(geometry, material), [geometry, material]);
  return <primitive object={line} />;
}

function DataParticle({ index }: { index: number }) {
  const mesh = useRef<THREE.Mesh>(null);
  const route = index % 3;
  const end: [number, number, number] =
    route === 0 ? [-1.85, -0.6, -0.35] : route === 1 ? [1.7, -0.45, -0.2] : [0.55, 1.15, -0.55];
  const color = route === 0 ? COLORS.cache : route === 1 ? COLORS.amd : COLORS.fireworks;

  useFrame(({ clock }) => {
    if (!mesh.current) return;
    const t = (clock.elapsedTime * (0.18 + route * 0.035) + index * 0.073) % 1;
    const lift = Math.sin(t * Math.PI) * 0.32;
    mesh.current.position.set(end[0] * t, 0.1 + (end[1] - 0.1) * t + lift, end[2] * t);
  });

  return (
    <mesh ref={mesh}>
      <sphereGeometry args={[0.035, 12, 12]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.4} />
    </mesh>
  );
}

function TopologyChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "cyan" | "green" | "amber" | "purple";
}) {
  const tones = {
    cyan: "border-cyan-300/30 bg-cyan-400/10 text-cyan-100",
    green: "border-green-300/30 bg-green-400/10 text-green-100",
    amber: "border-amber-300/30 bg-amber-400/10 text-amber-100",
    purple: "border-fuchsia-300/30 bg-fuchsia-400/10 text-fuchsia-100",
  };
  return (
    <div className={`rounded-lg border px-3 py-2 backdrop-blur ${tones[tone]}`}>
      <div className="text-[10px] uppercase text-white/45">{label}</div>
      <div className="mt-0.5 truncate font-semibold">{value}</div>
    </div>
  );
}

function GridBackdrop() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 opacity-40"
      style={{
        backgroundImage:
          "linear-gradient(rgba(255,255,255,0.07) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.07) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
      }}
    />
  );
}
