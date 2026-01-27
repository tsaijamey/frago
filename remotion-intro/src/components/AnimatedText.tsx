import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import { colors, fonts, gradientText, springConfigs } from "../styles";

// 打字机效果组件
export const Typewriter: React.FC<{
  text: string;
  startFrame?: number;
  charFrames?: number;
  showCursor?: boolean;
  style?: React.CSSProperties;
}> = ({ text, startFrame = 0, charFrames = 2, showCursor = true, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const adjustedFrame = Math.max(0, frame - startFrame);
  const visibleChars = Math.min(
    text.length,
    Math.floor(adjustedFrame / charFrames)
  );

  // 光标闪烁
  const cursorOpacity = interpolate(
    (frame % 16),
    [0, 8, 16],
    [1, 0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const isTyping = visibleChars < text.length;

  return (
    <span style={style}>
      {text.slice(0, visibleChars)}
      {showCursor && (
        <span
          style={{
            opacity: isTyping ? 1 : cursorOpacity,
            color: colors.accent,
            fontWeight: 400,
          }}
        >
          |
        </span>
      )}
    </span>
  );
};

// 高亮划线效果
export const HighlightText: React.FC<{
  children: React.ReactNode;
  delay?: number;
  color?: string;
  duration?: number;
}> = ({ children, delay = 0, color = colors.accent, duration = 20 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame,
    fps,
    config: springConfigs.smooth,
    delay,
    durationInFrames: duration,
  });

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <span
        style={{
          position: "absolute",
          left: -4,
          right: -4,
          top: "50%",
          height: "1.1em",
          transform: `translateY(-50%) scaleX(${progress})`,
          transformOrigin: "left center",
          backgroundColor: `${color}30`,
          borderRadius: 6,
          zIndex: 0,
        }}
      />
      <span style={{ position: "relative", zIndex: 1, color }}>{children}</span>
    </span>
  );
};

// 渐变动画文字
export const GradientText: React.FC<{
  children: React.ReactNode;
  delay?: number;
  style?: React.CSSProperties;
}> = ({ children, delay = 0, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const opacity = interpolate(
    frame,
    [delay, delay + 0.5 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.quad) }
  );

  const y = spring({
    frame: frame - delay,
    fps,
    config: springConfigs.snappy,
  });

  const translateY = interpolate(y, [0, 1], [40, 0]);

  return (
    <span
      style={{
        ...gradientText,
        ...style,
        opacity,
        transform: `translateY(${translateY}px)`,
        display: "inline-block",
      }}
    >
      {children}
    </span>
  );
};

// 逐字母入场动画
export const AnimatedLetters: React.FC<{
  text: string;
  delay?: number;
  staggerFrames?: number;
  style?: React.CSSProperties;
}> = ({ text, delay = 0, staggerFrames = 2, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <span style={style}>
      {text.split("").map((char, i) => {
        const charDelay = delay + i * staggerFrames;
        const progress = spring({
          frame: frame - charDelay,
          fps,
          config: springConfigs.bouncy,
        });

        const opacity = interpolate(progress, [0, 1], [0, 1]);
        const y = interpolate(progress, [0, 1], [20, 0]);
        const scale = interpolate(progress, [0, 0.5, 1], [0.5, 1.2, 1]);

        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              opacity,
              transform: `translateY(${y}px) scale(${scale})`,
              whiteSpace: char === " " ? "pre" : undefined,
            }}
          >
            {char}
          </span>
        );
      })}
    </span>
  );
};

// 数字计数动画
export const CountUp: React.FC<{
  from: number;
  to: number;
  delay?: number;
  duration?: number;
  suffix?: string;
  decimals?: number;
  style?: React.CSSProperties;
}> = ({ from, to, delay = 0, duration = 30, suffix = "", decimals = 0, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = interpolate(
    frame,
    [delay, delay + duration],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.exp),
    }
  );

  const value = interpolate(progress, [0, 1], [from, to]);

  return (
    <span style={style}>
      {value.toFixed(decimals)}{suffix}
    </span>
  );
};
