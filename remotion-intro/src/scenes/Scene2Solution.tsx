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
import { AnimatedLetters, GradientText } from "../components/AnimatedText";

export const Scene2Solution: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo 爆炸入场
  const logoDelay = 0;
  const logoScale = spring({
    frame: frame - logoDelay,
    fps,
    config: { damping: 10, stiffness: 150 },
  });

  const logoRotate = interpolate(
    spring({
      frame: frame - logoDelay,
      fps,
      config: springConfigs.bouncy,
    }),
    [0, 1],
    [-10, 0]
  );

  // Logo 发光脉冲
  const glowPulse = interpolate(
    frame % 60,
    [0, 30, 60],
    [0.5, 1, 0.5]
  );

  // 主标题
  const titleDelay = 0.6 * fps;
  const titleOpacity = interpolate(
    frame,
    [titleDelay, titleDelay + 0.4 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.quad) }
  );

  const titleY = spring({
    frame: frame - titleDelay,
    fps,
    config: springConfigs.snappy,
  });

  // 副标题
  const subtitleDelay = 1.3 * fps;
  const subtitleOpacity = interpolate(
    frame,
    [subtitleDelay, subtitleDelay + 0.5 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // "记住" 高亮效果
  const highlightDelay = 1 * fps;
  const highlightProgress = spring({
    frame: frame - highlightDelay,
    fps,
    config: springConfigs.smooth,
    durationInFrames: 25,
  });

  return (
    <AbsoluteFill style={fullScreen}>
      <SceneBackground variant="default" />

      {/* frago Logo */}
      <div
        style={{
          fontSize: 160,
          fontWeight: 800,
          letterSpacing: "-0.02em",
          transform: `scale(${logoScale}) rotate(${logoRotate}deg)`,
          marginBottom: 40,
          position: "relative",
        }}
      >
        {/* 发光层 */}
        <span
          style={{
            position: "absolute",
            inset: 0,
            ...gradientText,
            filter: `blur(30px)`,
            opacity: glowPulse,
          }}
        >
          frago
        </span>
        {/* 主文字 */}
        <span style={gradientText}>frago</span>
      </div>

      {/* 主标题 */}
      <div
        style={{
          fontSize: 56,
          fontWeight: 600,
          color: colors.text,
          opacity: titleOpacity,
          transform: `translateY(${interpolate(titleY, [0, 1], [40, 0])}px)`,
          marginBottom: 24,
          textAlign: "center",
        }}
      >
        让 AI 学会
        <span
          style={{
            position: "relative",
            display: "inline-block",
            marginLeft: 12,
          }}
        >
          {/* 高亮背景 */}
          <span
            style={{
              position: "absolute",
              left: -8,
              right: -8,
              top: "50%",
              height: "1.15em",
              transform: `translateY(-50%) scaleX(${highlightProgress})`,
              transformOrigin: "left center",
              background: `linear-gradient(90deg, ${colors.primary}40, ${colors.accent}40)`,
              borderRadius: 8,
              zIndex: 0,
            }}
          />
          <span
            style={{
              position: "relative",
              zIndex: 1,
              ...gradientText,
              fontWeight: 700,
            }}
          >
            记住
          </span>
        </span>
      </div>

      {/* 副标题 */}
      <div
        style={{
          fontSize: 28,
          fontWeight: 400,
          color: colors.textMuted,
          opacity: subtitleOpacity,
          letterSpacing: "0.05em",
        }}
      >
        探索一次 · 记住方法 · 之后秒执行
      </div>

      {/* 装饰线条 */}
      <div
        style={{
          position: "absolute",
          bottom: 120,
          display: "flex",
          gap: 12,
          opacity: subtitleOpacity,
        }}
      >
        {[colors.primary, colors.accent, colors.primaryLight].map((color, i) => (
          <div
            key={i}
            style={{
              width: 40,
              height: 4,
              borderRadius: 2,
              backgroundColor: color,
              transform: `scaleX(${spring({
                frame: frame - subtitleDelay - i * 5,
                fps,
                config: springConfigs.snappy,
              })})`,
            }}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};
