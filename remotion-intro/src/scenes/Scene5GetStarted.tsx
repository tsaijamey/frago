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
import { Typewriter } from "../components/AnimatedText";

// 终端命令行组件
const TerminalLine: React.FC<{
  command: string;
  delay: number;
  frame: number;
  fps: number;
  charFrames?: number;
}> = ({ command, delay, frame, fps, charFrames = 2 }) => {
  const lineProgress = spring({
    frame: frame - delay,
    fps,
    config: springConfigs.smooth,
  });

  const opacity = interpolate(lineProgress, [0, 1], [0, 1]);
  const x = interpolate(lineProgress, [0, 1], [-20, 0]);

  return (
    <div
      style={{
        opacity,
        transform: `translateX(${x}px)`,
        marginBottom: 16,
        display: "flex",
        alignItems: "center",
      }}
    >
      <span
        style={{
          color: colors.accent,
          marginRight: 12,
          fontWeight: 600,
        }}
      >
        $
      </span>
      <Typewriter
        text={command}
        startFrame={delay + 5}
        charFrames={charFrames}
        showCursor={true}
        style={{ color: colors.text }}
      />
    </div>
  );
};

export const Scene5GetStarted: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 标题动画
  const titleOpacity = interpolate(
    frame,
    [0, 0.4 * fps],
    [0, 1],
    { extrapolateRight: "clamp", easing: Easing.out(Easing.quad) }
  );

  const titleScale = spring({
    frame,
    fps,
    config: springConfigs.bouncy,
  });

  // 终端框动画
  const terminalDelay = 0.5 * fps;
  const terminalProgress = spring({
    frame: frame - terminalDelay,
    fps,
    config: springConfigs.snappy,
  });

  const terminalOpacity = interpolate(terminalProgress, [0, 1], [0, 1]);
  const terminalY = interpolate(terminalProgress, [0, 1], [40, 0]);
  const terminalScale = interpolate(terminalProgress, [0, 1], [0.95, 1]);

  // 底部提示（命令打字完成后出现，约 3.2s）
  const tipDelay = 3.2 * fps;
  const tipOpacity = interpolate(
    frame,
    [tipDelay, tipDelay + 0.4 * fps],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={fullScreen}>
      <SceneBackground variant="accent" />

      {/* 标题 */}
      <div
        style={{
          fontSize: 56,
          fontWeight: 700,
          color: colors.text,
          opacity: titleOpacity,
          transform: `scale(${interpolate(titleScale, [0, 1], [0.9, 1])})`,
          marginBottom: 50,
          textAlign: "center",
        }}
      >
        <span style={gradientText}>三行命令</span>
        <span style={{ marginLeft: 12 }}>立即开始</span>
      </div>

      {/* 终端窗口 */}
      <div
        style={{
          opacity: terminalOpacity,
          transform: `translateY(${terminalY}px) scale(${terminalScale})`,
          backgroundColor: "#0D0D12",
          borderRadius: 16,
          padding: "24px 32px 32px",
          minWidth: 700,
          fontFamily: fonts.mono,
          fontSize: 22,
          boxShadow: `
            0 25px 80px rgba(0,0,0,0.5),
            0 0 0 1px ${colors.border},
            inset 0 1px 0 rgba(255,255,255,0.05)
          `,
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* 终端顶部装饰光线 */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 1,
            background: `linear-gradient(90deg, transparent, ${colors.primary}50, ${colors.accent}50, transparent)`,
          }}
        />

        {/* 终端标题栏 */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 24,
          }}
        >
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: "50%",
              backgroundColor: "#ff5f56",
              boxShadow: "0 0 8px #ff5f5660",
            }}
          />
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: "50%",
              backgroundColor: "#ffbd2e",
              boxShadow: "0 0 8px #ffbd2e60",
            }}
          />
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: "50%",
              backgroundColor: "#27ca40",
              boxShadow: "0 0 8px #27ca4060",
            }}
          />
          <span
            style={{
              marginLeft: 16,
              fontSize: 14,
              color: colors.textDim,
            }}
          >
            Terminal
          </span>
        </div>

        {/* 命令行 */}
        <TerminalLine
          command="uv tool install frago-cli"
          delay={0.8 * fps}
          frame={frame}
          fps={fps}
        />
        <TerminalLine
          command="frago init"
          delay={1.4 * fps}
          frame={frame}
          fps={fps}
        />
        <TerminalLine
          command="frago server start"
          delay={1.9 * fps}
          frame={frame}
          fps={fps}
        />
      </div>

      {/* 底部提示 */}
      <div
        style={{
          marginTop: 50,
          display: "flex",
          alignItems: "center",
          gap: 12,
          opacity: tipOpacity,
        }}
      >
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: colors.accent,
            boxShadow: `0 0 10px ${colors.accent}`,
          }}
        />
        <span
          style={{
            fontSize: 22,
            color: colors.textMuted,
          }}
        >
          打开浏览器
        </span>
        <span
          style={{
            fontSize: 22,
            color: colors.accent,
            fontFamily: fonts.mono,
            backgroundColor: `${colors.accent}15`,
            padding: "6px 14px",
            borderRadius: 8,
          }}
        >
          http://127.0.0.1:8093
        </span>
        <span
          style={{
            fontSize: 22,
            color: colors.textMuted,
          }}
        >
          即可使用
        </span>
      </div>
    </AbsoluteFill>
  );
};
