import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import { colors, fonts, fullScreen, springConfigs } from "../styles";
import { SceneBackground } from "../components/Background";
import { AnimatedLetters, HighlightText } from "../components/AnimatedText";

export const Scene1Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 标题入场
  const titleOpacity = interpolate(
    frame,
    [0, 0.5 * fps],
    [0, 1],
    { extrapolateRight: "clamp", easing: Easing.out(Easing.quad) }
  );

  const titleY = spring({
    frame,
    fps,
    config: springConfigs.snappy,
  });

  // 循环图标动画
  const iconDelay = 0.8 * fps;
  const iconProgress = spring({
    frame: frame - iconDelay,
    fps,
    config: springConfigs.bouncy,
  });

  // 持续旋转
  const rotation = interpolate(
    frame,
    [iconDelay, iconDelay + 3 * fps],
    [0, 720],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.quad) }
  );

  // 脉冲效果
  const pulse = interpolate(
    (frame - iconDelay) % 30,
    [0, 15, 30],
    [1, 1.1, 1]
  );

  // 副标题
  const subtitleDelay = 1.8 * fps;
  const subtitleOpacity = interpolate(
    frame,
    [subtitleDelay, subtitleDelay + 0.5 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const subtitleY = spring({
    frame: frame - subtitleDelay,
    fps,
    config: springConfigs.smooth,
  });

  return (
    <AbsoluteFill style={fullScreen}>
      <SceneBackground variant="warm" />

      {/* 主标题 */}
      <div
        style={{
          fontSize: 72,
          fontWeight: 700,
          color: colors.text,
          opacity: titleOpacity,
          transform: `translateY(${interpolate(titleY, [0, 1], [50, 0])}px)`,
          marginBottom: 60,
          textAlign: "center",
          lineHeight: 1.2,
        }}
      >
        每次让 AI 做
        <HighlightText delay={0.5 * fps} color={colors.warning}>
          同一件事
        </HighlightText>
        ...
      </div>

      {/* 循环图标 */}
      <div
        style={{
          opacity: iconProgress,
          transform: `rotate(${rotation}deg) scale(${iconProgress * pulse})`,
          marginBottom: 60,
        }}
      >
        <svg
          width="140"
          height="140"
          viewBox="0 0 24 24"
          fill="none"
          stroke={colors.warning}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            filter: `drop-shadow(0 0 20px ${colors.warning}80)`,
          }}
        >
          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
        </svg>
      </div>

      {/* 副标题 */}
      <div
        style={{
          fontSize: 42,
          fontWeight: 500,
          color: colors.warning,
          opacity: subtitleOpacity,
          transform: `translateY(${interpolate(subtitleY, [0, 1], [30, 0])}px)`,
          textShadow: `0 0 40px ${colors.warning}60`,
        }}
      >
        它都要从头开始探索
      </div>

      {/* Token 消耗提示 */}
      <div
        style={{
          position: "absolute",
          bottom: 100,
          fontSize: 24,
          color: colors.textDim,
          opacity: interpolate(
            frame,
            [2.5 * fps, 3 * fps],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
          ),
        }}
      >
        每次消耗 150,000+ tokens
      </div>
    </AbsoluteFill>
  );
};
