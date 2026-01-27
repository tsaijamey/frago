import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { colors } from "../styles";

// 动态网格背景
export const GridBackground: React.FC<{
  opacity?: number;
}> = ({ opacity = 0.03 }) => {
  return (
    <AbsoluteFill
      style={{
        backgroundImage: `
          linear-gradient(${colors.border} 1px, transparent 1px),
          linear-gradient(90deg, ${colors.border} 1px, transparent 1px)
        `,
        backgroundSize: "60px 60px",
        opacity,
      }}
    />
  );
};

// 发光圆球
export const GlowOrb: React.FC<{
  x: string;
  y: string;
  size: number;
  color: string;
  blur?: number;
  pulseSpeed?: number;
}> = ({ x, y, size, color, blur = 100, pulseSpeed = 60 }) => {
  const frame = useCurrentFrame();

  const pulse = interpolate(
    frame % pulseSpeed,
    [0, pulseSpeed / 2, pulseSpeed],
    [1, 1.2, 1]
  );

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${color}60 0%, transparent 70%)`,
        filter: `blur(${blur}px)`,
        transform: `translate(-50%, -50%) scale(${pulse})`,
      }}
    />
  );
};

// 渐变背景
export const GradientBackground: React.FC<{
  angle?: number;
  animated?: boolean;
}> = ({ angle = 135, animated = true }) => {
  const frame = useCurrentFrame();

  const animatedAngle = animated
    ? angle + interpolate(frame, [0, 300], [0, 30], { extrapolateRight: "extend" })
    : angle;

  return (
    <AbsoluteFill
      style={{
        background: `
          linear-gradient(${animatedAngle}deg,
            ${colors.background} 0%,
            ${colors.backgroundLight} 50%,
            ${colors.background} 100%
          )
        `,
      }}
    />
  );
};

// 粒子效果（简化版）
export const ParticleField: React.FC<{
  count?: number;
}> = ({ count = 30 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // 使用固定种子生成粒子位置
  const particles = Array.from({ length: count }, (_, i) => {
    const seed = i * 137.5;
    return {
      x: ((seed * 7) % 100),
      y: ((seed * 13) % 100),
      size: 2 + (seed % 4),
      speed: 0.3 + (seed % 0.5),
      opacity: 0.1 + ((seed * 3) % 0.3),
    };
  });

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {particles.map((p, i) => {
        const y = (p.y + frame * p.speed * 0.1) % 120 - 10;

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${p.x}%`,
              top: `${y}%`,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              backgroundColor: colors.primary,
              opacity: p.opacity,
            }}
          />
        );
      })}
    </AbsoluteFill>
  );
};

// 组合背景
export const SceneBackground: React.FC<{
  variant?: "default" | "accent" | "warm";
}> = ({ variant = "default" }) => {
  const orbConfigs = {
    default: [
      { x: "20%", y: "30%", size: 400, color: colors.primary },
      { x: "80%", y: "70%", size: 300, color: colors.accent },
    ],
    accent: [
      { x: "70%", y: "20%", size: 500, color: colors.accent },
      { x: "30%", y: "80%", size: 350, color: colors.primary },
    ],
    warm: [
      { x: "50%", y: "40%", size: 450, color: colors.warning },
      { x: "20%", y: "70%", size: 300, color: colors.danger },
    ],
  };

  const orbs = orbConfigs[variant];

  return (
    <>
      <GradientBackground />
      <GridBackground />
      {orbs.map((orb, i) => (
        <GlowOrb key={i} {...orb} pulseSpeed={80 + i * 20} />
      ))}
      <ParticleField count={20} />
    </>
  );
};
