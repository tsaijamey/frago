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

type StepProps = {
  number: string;
  command: string;
  description: string;
  color: string;
  delay: number;
  frame: number;
  fps: number;
  isActive: boolean;
};

const Step: React.FC<StepProps> = ({
  number,
  command,
  description,
  color,
  delay,
  frame,
  fps,
  isActive,
}) => {
  const progress = spring({
    frame: frame - delay,
    fps,
    config: springConfigs.bouncy,
  });

  const scale = interpolate(progress, [0, 1], [0.8, 1]);
  const opacity = interpolate(progress, [0, 1], [0, 1]);
  const x = interpolate(progress, [0, 1], [-80, 0]);

  // 活跃状态的发光效果
  const glowIntensity = isActive
    ? interpolate((frame - delay) % 40, [0, 20, 40], [0.3, 0.6, 0.3])
    : 0;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 30,
        opacity,
        transform: `translateX(${x}px) scale(${scale})`,
        marginBottom: 30,
        padding: "20px 30px",
        borderRadius: 16,
        backgroundColor: isActive ? `${color}15` : "transparent",
        border: isActive ? `1px solid ${color}40` : "1px solid transparent",
        boxShadow: isActive ? `0 0 40px ${color}${Math.round(glowIntensity * 255).toString(16).padStart(2, '0')}` : "none",
      }}
    >
      {/* 数字圆圈 */}
      <div
        style={{
          width: 70,
          height: 70,
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${color}, ${color}80)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 32,
          fontWeight: 700,
          color: colors.text,
          flexShrink: 0,
          boxShadow: `0 0 30px ${color}50`,
        }}
      >
        {number}
      </div>

      {/* 内容 */}
      <div>
        <div
          style={{
            fontSize: 28,
            fontWeight: 600,
            color: colors.text,
            fontFamily: fonts.mono,
            marginBottom: 8,
            letterSpacing: "-0.02em",
          }}
        >
          {command}
        </div>
        <div
          style={{
            fontSize: 20,
            color: colors.textMuted,
            fontWeight: 400,
          }}
        >
          {description}
        </div>
      </div>
    </div>
  );
};

// 连接线组件
const Connector: React.FC<{
  delay: number;
  frame: number;
  fps: number;
}> = ({ delay, frame, fps }) => {
  const progress = spring({
    frame: frame - delay,
    fps,
    config: springConfigs.smooth,
    durationInFrames: 15,
  });

  return (
    <div
      style={{
        marginLeft: 55,
        height: 30,
        width: 2,
        background: `linear-gradient(180deg, ${colors.primary}, ${colors.accent})`,
        transform: `scaleY(${progress})`,
        transformOrigin: "top",
        opacity: 0.5,
      }}
    />
  );
};

export const Scene3Workflow: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 标题动画
  const titleOpacity = interpolate(
    frame,
    [0, 0.4 * fps],
    [0, 1],
    { extrapolateRight: "clamp", easing: Easing.out(Easing.quad) }
  );

  const titleY = spring({
    frame,
    fps,
    config: springConfigs.snappy,
  });

  // 计算当前活跃的步骤
  const step1Active = frame >= 0.8 * fps && frame < 2.5 * fps;
  const step2Active = frame >= 2.5 * fps && frame < 4.2 * fps;
  const step3Active = frame >= 4.2 * fps;

  return (
    <AbsoluteFill style={fullScreen}>
      <SceneBackground variant="accent" />

      {/* 标题 */}
      <div
        style={{
          fontSize: 52,
          fontWeight: 700,
          color: colors.text,
          opacity: titleOpacity,
          transform: `translateY(${interpolate(titleY, [0, 1], [30, 0])}px)`,
          marginBottom: 60,
          textAlign: "center",
        }}
      >
        <span style={gradientText}>三步</span>
        <span style={{ marginLeft: 12 }}>完成自动化</span>
      </div>

      {/* 步骤列表 */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
        <Step
          number="1"
          command="/frago.run"
          description="探索任务，AI 自动记录过程"
          color={colors.primary}
          delay={0.8 * fps}
          frame={frame}
          fps={fps}
          isActive={step1Active}
        />

        <Connector delay={1.8 * fps} frame={frame} fps={fps} />

        <Step
          number="2"
          command="/frago.recipe"
          description="固化经验，生成可复用配方"
          color={colors.accent}
          delay={2.5 * fps}
          frame={frame}
          fps={fps}
          isActive={step2Active}
        />

        <Connector delay={3.5 * fps} frame={frame} fps={fps} />

        <Step
          number="3"
          command="/frago.test"
          description="验证配方，确保可靠运行"
          color="#8B5CF6"
          delay={4.2 * fps}
          frame={frame}
          fps={fps}
          isActive={step3Active}
        />
      </div>
    </AbsoluteFill>
  );
};
