import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import { colors, fonts, fullScreen, gradientText, springConfigs } from "../styles";
import { SceneBackground } from "../components/Background";
import { CountUp } from "../components/AnimatedText";

// 对比卡片组件
const ComparisonCard: React.FC<{
  title: string;
  value: string;
  unit: string;
  note: string;
  color: string;
  isPositive: boolean;
  delay: number;
  frame: number;
  fps: number;
}> = ({ title, value, unit, note, color, isPositive, delay, frame, fps }) => {
  const progress = spring({
    frame: frame - delay,
    fps,
    config: springConfigs.bouncy,
  });

  const scale = interpolate(progress, [0, 1], [0.85, 1]);
  const opacity = interpolate(progress, [0, 1], [0, 1]);
  const y = interpolate(progress, [0, 1], [50, 0]);

  // 发光脉冲（仅正面卡片）
  const glowPulse = isPositive
    ? interpolate((frame - delay) % 50, [0, 25, 50], [0.3, 0.6, 0.3])
    : 0;

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
        textAlign: "center",
        padding: "50px 60px",
        borderRadius: 24,
        backgroundColor: colors.backgroundCard,
        border: isPositive ? `2px solid ${color}60` : `1px solid ${colors.border}`,
        minWidth: 340,
        boxShadow: isPositive
          ? `0 0 60px ${color}${Math.round(glowPulse * 255).toString(16).padStart(2, '0')}, inset 0 1px 0 ${color}30`
          : `0 10px 40px rgba(0,0,0,0.3)`,
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* 背景装饰 */}
      {isPositive && (
        <div
          style={{
            position: "absolute",
            top: -50,
            right: -50,
            width: 150,
            height: 150,
            borderRadius: "50%",
            background: `radial-gradient(circle, ${color}20, transparent)`,
          }}
        />
      )}

      <div
        style={{
          fontSize: 22,
          color: colors.textMuted,
          marginBottom: 20,
          fontWeight: 500,
        }}
      >
        {title}
      </div>

      <div
        style={{
          fontSize: 72,
          fontWeight: 800,
          color: color,
          marginBottom: 8,
          textShadow: isPositive ? `0 0 30px ${color}60` : "none",
        }}
      >
        {value}
      </div>

      <div
        style={{
          fontSize: 18,
          color: colors.textDim,
          marginBottom: 20,
        }}
      >
        {unit}
      </div>

      <div
        style={{
          fontSize: 16,
          color: isPositive ? color : colors.textDim,
          fontWeight: 500,
          padding: "8px 16px",
          borderRadius: 20,
          backgroundColor: isPositive ? `${color}15` : "transparent",
          display: "inline-block",
        }}
      >
        {note}
      </div>
    </div>
  );
};

export const Scene4Comparison: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // VS 动画
  const vsDelay = 0.8 * fps;
  const vsOpacity = interpolate(
    frame,
    [vsDelay, vsDelay + 0.3 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const vsScale = spring({
    frame: frame - vsDelay,
    fps,
    config: springConfigs.bouncy,
  });

  // 节省比例
  const savingDelay = 2 * fps;
  const savingProgress = spring({
    frame: frame - savingDelay,
    fps,
    config: springConfigs.snappy,
  });

  return (
    <AbsoluteFill style={fullScreen}>
      <SceneBackground variant="default" />

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 60,
          width: "100%",
          marginBottom: 80,
        }}
      >
        {/* 左侧 - 无 frago */}
        <ComparisonCard
          title="没有 frago"
          value="150k"
          unit="tokens / 每次"
          note="每次都要从头探索"
          color={colors.danger}
          isPositive={false}
          delay={0.3 * fps}
          frame={frame}
          fps={fps}
        />

        {/* VS */}
        <div
          style={{
            fontSize: 36,
            fontWeight: 800,
            color: colors.textDim,
            opacity: vsOpacity,
            transform: `scale(${interpolate(vsScale, [0, 1], [0.5, 1])}) rotate(${interpolate(vsScale, [0, 1], [-20, 0])}deg)`,
          }}
        >
          VS
        </div>

        {/* 右侧 - 有 frago */}
        <ComparisonCard
          title="使用 frago"
          value="2k"
          unit="tokens / 每次"
          note="直接执行配方"
          color={colors.accent}
          isPositive={true}
          delay={1.2 * fps}
          frame={frame}
          fps={fps}
        />
      </div>

      {/* 节省比例 */}
      <div
        style={{
          textAlign: "center",
          opacity: savingProgress,
          transform: `translateY(${interpolate(savingProgress, [0, 1], [30, 0])}px)`,
        }}
      >
        <div
          style={{
            fontSize: 24,
            color: colors.textMuted,
            marginBottom: 16,
            fontWeight: 500,
          }}
        >
          节省
        </div>
        <div
          style={{
            fontSize: 100,
            fontWeight: 800,
            ...gradientText,
            lineHeight: 1,
          }}
        >
          <CountUp
            from={0}
            to={98.7}
            delay={savingDelay}
            duration={40}
            decimals={1}
            suffix="%"
          />
        </div>
        <div
          style={{
            fontSize: 20,
            color: colors.textDim,
            marginTop: 16,
          }}
        >
          的 Token 成本
        </div>
      </div>
    </AbsoluteFill>
  );
};
